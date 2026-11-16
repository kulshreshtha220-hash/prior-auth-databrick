# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Refresh reference data (job: `pa_reference_refresh`, weekly)
# MAGIC Versioned Delta snapshots used by the adapters when a live MCP server is unavailable, and for
# MAGIC point-in-time audit ("which code set / policy version did we use?").
# MAGIC
# MAGIC | Table | Source |
# MAGIC |---|---|
# MAGIC | `ref_icd10cm` | CDC NCHS ICD-10-CM code descriptions (order file has the billable flag) |
# MAGIC | `ref_ncd`, `ref_lcd` | CMS Medicare Coverage Database exports |
# MAGIC | `ref_npi_cache` | NPPES NPI Registry API, for NPIs seen in `pa_requests` |
# MAGIC | `ref_hcpcs` | CMS HCPCS Level II file (optional URL) |
# MAGIC
# MAGIC Each source is independent: one failing download does not stop the others. URLs are widgets
# MAGIC because CMS/CDC rename files each year; check them at each code-set update (October).

# COMMAND ----------

dbutils.widgets.text("catalog", "db_certification")
dbutils.widgets.text("schema", "prior_auth")
dbutils.widgets.text("icd10_year", "2026")
dbutils.widgets.text("icd10_url", "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/{year}/icd10cm-Code%20Descriptions-{year}.zip")
dbutils.widgets.text("ncd_url", "https://downloads.cms.gov/medicare-coverage-database/downloads/exports/ncd.zip")
dbutils.widgets.text("lcd_url", "https://downloads.cms.gov/medicare-coverage-database/downloads/exports/current_lcd.zip")
dbutils.widgets.text("hcpcs_csv_url", "", "Optional HCPCS CSV URL")
dbutils.widgets.text("npi_max_age_days", "30")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
T = lambda t: f"`{catalog}`.`{schema}`.`{t}`"  # noqa: E731

# COMMAND ----------

import csv, datetime as dt, io, re, zipfile
import requests

now = dt.datetime.utcnow()
HEADERS = {"User-Agent": "pa-review-databricks/1.0 (reference refresh)"}
report = {}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=300)
    r.raise_for_status()
    return r.content

def all_files(blob):
    """Yield (name, bytes) for every file in a zip, descending into nested zips."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            data = z.read(n)
            if n.lower().endswith(".zip"):
                yield from all_files(data)
            else:
                yield n, data

# COMMAND ----------

# ICD-10-CM: order file is fixed width: order(5) code(7) billable(1) short(60) long
try:
    year = dbutils.widgets.get("icd10_year")
    blob = fetch(dbutils.widgets.get("icd10_url").format(year=year))
    order = next(d for n, d in all_files(blob) if re.search(r"order.*\.txt$", n, re.I))
    rows = []
    for line in order.decode("latin-1").splitlines():
        if len(line) < 16:
            continue
        code = line[6:13].strip()
        billable = line[14] == "1"
        desc = line[77:].strip() or line[16:76].strip()
        rows.append((code[:3] + ("." + code[3:] if len(code) > 3 else ""), desc, billable, f"ICD-10-CM FY{year}", now))
    spark.createDataFrame(rows, "code string, description string, billable boolean, code_set_version string, loaded_at timestamp") \
        .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T("ref_icd10cm"))
    report["ref_icd10cm"] = len(rows)
except Exception as e:
    report["ref_icd10cm"] = f"FAILED: {str(e)[:200]}"

# COMMAND ----------

def pick(cols, *patterns):
    for p in patterns:
        for c in cols:
            if re.search(p, c, re.I):
                return c
    return None

def load_policy_csvs(url, kind):
    blob = fetch(url)
    best = None
    for name, data in all_files(blob):
        if not name.lower().endswith(".csv"):
            continue
        reader = csv.DictReader(io.StringIO(data.decode("latin-1")))
        cols = reader.fieldnames or []
        idc = pick(cols, rf"^{kind}_id$", rf"{kind}.*id", r"^id$")
        title = pick(cols, r"title", r"sbjct", r"subject")
        if idc and title:
            rows = list(reader)
            if best is None or len(rows) > len(best[1]):
                best = (cols, rows, idc, title)
    if best is None:
        raise ValueError(f"No {kind.upper()} CSV with id/title columns found")
    cols, rows, idc, title = best
    ind = pick(cols, r"indicat", r"cvrg.*txt", r"coverage", r"txt$")
    url_c = pick(cols, r"url", r"link")
    eff = pick(cols, r"eff", r"date")
    contractor = pick(cols, r"contractor", r"cntrctr")
    clean = lambda s: re.sub(r"<[^>]+>", " ", s or "").strip()  # noqa: E731
    return [(r.get(idc), clean(r.get(title)), clean(r.get(ind))[:20000] if ind else "", r.get(url_c) if url_c else "",
             r.get(eff) if eff else "", r.get(contractor) if contractor else "") for r in rows]

for kind, url_w, table in [("ncd", "ncd_url", "ref_ncd"), ("lcd", "lcd_url", "ref_lcd")]:
    try:
        recs = load_policy_csvs(dbutils.widgets.get(url_w), kind)
        if kind == "ncd":
            df = spark.createDataFrame([(a, b, c, d, e, now) for a, b, c, d, e, _ in recs],
                                       "ncd_id string, title string, indications string, document_url string, effective_date string, loaded_at timestamp")
        else:
            df = spark.createDataFrame([(a, b, f, "", c, d, now) for a, b, c, d, e, f in recs],
                                       "lcd_id string, title string, contractor string, states string, indications string, document_url string, loaded_at timestamp")
        df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T(table))
        report[table] = len(recs)
    except Exception as e:
        report[table] = f"FAILED: {str(e)[:200]}"

# COMMAND ----------

# HCPCS (optional): CSV with code + description columns
hc_url = dbutils.widgets.get("hcpcs_csv_url").strip()
if hc_url:
    try:
        reader = csv.DictReader(io.StringIO(fetch(hc_url).decode("latin-1")))
        cols = reader.fieldnames or []
        c, d = pick(cols, r"hcpc", r"code"), pick(cols, r"long", r"desc")
        rows = [(r[c], r.get(d, ""), "active", hc_url.rsplit("/", 1)[-1], now) for r in reader if r.get(c)]
        spark.createDataFrame(rows, "code string, description string, status string, code_set_version string, loaded_at timestamp") \
            .write.mode("overwrite").saveAsTable(T("ref_hcpcs"))
        report["ref_hcpcs"] = len(rows)
    except Exception as e:
        report["ref_hcpcs"] = f"FAILED: {str(e)[:200]}"

# COMMAND ----------

# NPI cache: refresh NPIs seen in requests that are missing or older than N days
max_age = int(dbutils.widgets.get("npi_max_age_days"))
todo = [r.npi for r in spark.sql(f"""
    SELECT DISTINCT r.provider_npi AS npi FROM {T('pa_requests')} r
    LEFT JOIN {T('ref_npi_cache')} c ON c.npi = r.provider_npi
    WHERE r.provider_npi RLIKE '^[0-9]{{10}}$'
      AND (c.npi IS NULL OR c.fetched_at < current_timestamp() - INTERVAL {max_age} DAYS)
    LIMIT 2000""").collect()]
fetched = []
for npi in todo:
    try:
        j = requests.get("https://npiregistry.cms.hhs.gov/api/", params={"version": "2.1", "number": npi},
                         headers=HEADERS, timeout=30).json()
        res = (j.get("results") or [None])[0]
        if not res:
            fetched.append((npi, None, None, None, None, "not_found", now))
            continue
        b = res.get("basic", {})
        name = b.get("organization_name") or " ".join(x for x in [b.get("first_name"), b.get("last_name")] if x)
        tax = next((t for t in res.get("taxonomies", []) if t.get("primary")), (res.get("taxonomies") or [{}])[0])
        addr = (res.get("addresses") or [{}])[0]
        fetched.append((npi, name, tax.get("code"), tax.get("desc"), addr.get("state"),
                        "active" if b.get("status", "A") == "A" else "inactive", now))
    except Exception as e:
        print("NPI", npi, "failed:", str(e)[:100])
if fetched:
    spark.createDataFrame(fetched, "npi string, name string, taxonomy string, taxonomy_desc string, state string, status string, fetched_at timestamp") \
        .createOrReplaceTempView("npi_new")
    spark.sql(f"""MERGE INTO {T('ref_npi_cache')} t USING npi_new s ON t.npi = s.npi
                 WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
report["ref_npi_cache"] = len(fetched)

# COMMAND ----------

import json
print(json.dumps(report, indent=2, default=str))
failed = {k: v for k, v in report.items() if isinstance(v, str) and v.startswith("FAILED")}
if len(failed) == len(report):
    raise RuntimeError(f"All reference sources failed: {failed}")
dbutils.notebook.exit(json.dumps(report, default=str))
