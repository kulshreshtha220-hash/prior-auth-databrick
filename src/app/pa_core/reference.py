"""Unity Catalog reference-data tools (diagram: "MCP or adapter").

Used in two ways:
  * as the primary source when PA_DATA_SOURCES sets a server to "uc"
    (no call to the external MCP server), and
  * as the fallback when a live MCP server is unavailable.

Tables (created by the setup notebook, filled by the pa_reference_refresh job):
  ref_icd10cm(code, description, billable, code_set_version)      CDC ICD-10-CM
  ref_ncd(ncd_id, title, indications, document_url, effective_date) CMS MCD
  ref_lcd(lcd_id, title, contractor, states, indications, document_url) CMS MCD
  ref_npi_cache(npi, name, taxonomy, taxonomy_desc, state, status, fetched_at)
      filled on demand from the free public NPPES API and cached in UC
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from . import sql

logger = logging.getLogger(__name__)
NPPES_API = "https://npiregistry.cms.hhs.gov/api/"
NPI_CACHE_MAX_AGE_DAYS = 30

ADAPTER_TOOLS: dict[str, list[dict]] = {
    "icd10_codes": [
        {
            "name": "ref_icd10_lookup",
            "description": "Validate ICD-10-CM diagnosis codes against the official code set stored in Unity Catalog. "
            "For each code returns: found (valid), description, billable, code_set_version, and for a "
            "non-billable category code the billable child codes. Use this for every diagnosis code.",
            "parameters": {
                "type": "object",
                "properties": {"codes": {"type": "array", "items": {"type": "string"},
                                         "description": "ICD-10-CM codes, e.g. ['R91.1','J18.9']"}},
                "required": ["codes"],
            },
        }
    ],
    "npi_registry": [
        {
            "name": "ref_npi_lookup",
            "description": "Verify a provider NPI: checks the NPI check digit, then returns name, primary taxonomy "
            "(specialty), state and status (active / inactive / not_found) from the NPPES registry "
            "(cached in Unity Catalog).",
            "parameters": {
                "type": "object",
                "properties": {"npi": {"type": "string", "description": "10-digit NPI"}},
                "required": ["npi"],
            },
        }
    ],
    "cms_coverage": [
        {
            "name": "ref_coverage_search",
            "description": "Search Medicare National (NCD) and Local (LCD) Coverage Determinations stored in Unity "
            "Catalog by keywords (procedure name, condition). Returns up to 10 policies with id, type, title "
            "and the start of the indications text.",
            "parameters": {
                "type": "object",
                "properties": {"keywords": {"type": "string", "description": "e.g. 'bronchoscopy lung biopsy'"}},
                "required": ["keywords"],
            },
        },
        {
            "name": "ref_coverage_document",
            "description": "Get the full indications / coverage criteria text of one NCD or LCD by its id "
            "(as returned by ref_coverage_search).",
            "parameters": {
                "type": "object",
                "properties": {"policy_id": {"type": "string"}, "type": {"type": "string", "enum": ["NCD", "LCD"]}},
                "required": ["policy_id", "type"],
            },
        },
    ],
}

# How the SKILL.md tool names map to the UC tools (told to the agents).
SKILL_TOOL_MAP = {
    "icd10_codes": "validate_code / lookup_code / get_hierarchy -> ref_icd10_lookup",
    "npi_registry": "npi_validate / npi_lookup -> ref_npi_lookup",
    "cms_coverage": "search_national_coverage / search_local_coverage -> ref_coverage_search; "
                    "get_coverage_document / batch_get_ncds -> ref_coverage_document",
}


def _clean_code(c: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(c).upper())


def npi_check_digit_ok(npi: str) -> bool:
    """NPI check digit: Luhn over '80840' + first 9 digits."""
    if not re.fullmatch(r"\d{10}", npi or ""):
        return False
    digits = [int(d) for d in "80840" + npi[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(npi[9])


def _icd10_lookup(args: dict) -> dict:
    codes = [c for c in (_clean_code(x) for x in args.get("codes", [])) if c][:25]
    rows = sql.execute(
        f"SELECT code, description, billable, code_set_version FROM {sql.table('ref_icd10cm')} "
        "WHERE replace(code, '.', '') IN (SELECT explode(from_json(:codes, 'array<string>')))",
        {"codes": codes},
    )
    by_code = {_clean_code(r["code"]): r for r in rows}
    out = []
    for c in codes:
        r = by_code.get(c)
        if not r:
            out.append({"code": c, "found": False, "valid": False, "billable": False,
                        "note": "not in the ICD-10-CM code set"})
            continue
        billable = str(r.get("billable")).lower() == "true"
        item = {"code": r["code"], "found": True, "valid": True, "billable": billable,
                "description": r["description"], "code_set_version": r["code_set_version"]}
        if not billable:
            kids = sql.execute(
                f"SELECT code, description FROM {sql.table('ref_icd10cm')} "
                "WHERE billable AND replace(code, '.', '') LIKE concat(:c, '%') ORDER BY code LIMIT 10",
                {"c": c},
            )
            item["billable_children"] = kids
            item["note"] = "category code, not billable: a more specific child code is required"
        out.append(item)
    return {"results": out, "source": "Unity Catalog ref_icd10cm"}


def _nppes_fetch(npi: str) -> dict | None:
    import httpx

    r = httpx.get(NPPES_API, params={"version": "2.1", "number": npi}, timeout=20,
                  headers={"User-Agent": "pa-review-databricks/1.0"})
    r.raise_for_status()
    res = (r.json().get("results") or [None])[0]
    if not res:
        return {"npi": npi, "status": "not_found"}
    b = res.get("basic", {})
    name = b.get("organization_name") or " ".join(x for x in [b.get("first_name"), b.get("last_name")] if x)
    if b.get("credential"):
        name += f", {b['credential']}"
    taxes = res.get("taxonomies") or [{}]
    tax = next((t for t in taxes if t.get("primary")), taxes[0])
    addr = (res.get("addresses") or [{}])[0]
    return {"npi": npi, "name": name, "taxonomy": tax.get("code"), "taxonomy_desc": tax.get("desc"),
            "state": addr.get("state"), "status": "active" if b.get("status", "A") == "A" else "inactive"}


def _npi_lookup(args: dict) -> dict:
    npi = re.sub(r"\D", "", str(args.get("npi", "")))
    if not npi_check_digit_ok(npi):
        return {"npi": npi, "status": "invalid", "check_digit_valid": False,
                "note": "not a valid NPI (10 digits with a correct check digit)"}
    rows = sql.execute(
        f"SELECT npi, name, taxonomy, taxonomy_desc, state, status, CAST(fetched_at AS STRING) AS fetched_at "
        f"FROM {sql.table('ref_npi_cache')} WHERE npi = :npi "
        f"AND fetched_at >= current_timestamp() - INTERVAL {NPI_CACHE_MAX_AGE_DAYS} DAYS LIMIT 1",
        {"npi": npi},
    )
    if rows:
        return {**rows[0], "check_digit_valid": True, "source": "Unity Catalog ref_npi_cache"}
    rec = _nppes_fetch(npi)
    try:  # cache for next time (needs MODIFY on ref_npi_cache)
        sql.execute(
            f"MERGE INTO {sql.table('ref_npi_cache')} t USING (SELECT :npi AS npi, :name AS name, :taxonomy AS taxonomy, "
            ":taxonomy_desc AS taxonomy_desc, :state AS state, :status AS status, current_timestamp() AS fetched_at) s "
            "ON t.npi = s.npi WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *",
            {k: rec.get(k) for k in ("npi", "name", "taxonomy", "taxonomy_desc", "state", "status")},
        )
    except Exception as e:  # noqa: BLE001 - caching is best effort
        logger.warning("NPI cache write failed: %s", e)
    return {**rec, "check_digit_valid": True, "source": "NPPES registry (cached to Unity Catalog)",
            "fetched_at": datetime.now(timezone.utc).isoformat()}


def _coverage_search(args: dict) -> dict:
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", str(args.get("keywords", "")).lower()) if len(w) > 2][:6]
    if not words:
        return {"results": []}
    score = " + ".join(f"(CASE WHEN lower(concat(title, ' ', coalesce(indications, ''))) LIKE :w{i} THEN 1 ELSE 0 END)"
                       for i in range(len(words)))
    params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
    rows = sql.execute(
        f"""SELECT * FROM (
              SELECT 'NCD' AS type, ncd_id AS policy_id, title, substr(indications, 1, 800) AS indications_start,
                     document_url, ({score}) AS score FROM {sql.table('ref_ncd')}
              UNION ALL
              SELECT 'LCD', lcd_id, title, substr(indications, 1, 800), document_url, ({score})
              FROM {sql.table('ref_lcd')})
            WHERE score > 0 ORDER BY score DESC LIMIT 10""",
        params,
    )
    return {"results": rows, "source": "Unity Catalog ref_ncd / ref_lcd",
            "note": "No rows means no specific NCD/LCD matched: evaluate general medical necessity (Path B)."}


def _coverage_document(args: dict) -> dict:
    kind = str(args.get("type", "NCD")).upper()
    table, id_col = ("ref_lcd", "lcd_id") if kind == "LCD" else ("ref_ncd", "ncd_id")
    rows = sql.execute(
        f"SELECT {id_col} AS policy_id, title, substr(indications, 1, 15000) AS indications, document_url "
        f"FROM {sql.table(table)} WHERE {id_col} = :id LIMIT 1",
        {"id": str(args.get("policy_id", ""))[:40]},
    )
    return {"result": rows[0] if rows else None, "type": kind, "source": f"Unity Catalog {table}"}


_DISPATCH = {
    "ref_icd10_lookup": _icd10_lookup,
    "ref_npi_lookup": _npi_lookup,
    "ref_coverage_search": _coverage_search,
    "ref_coverage_document": _coverage_document,
}


def call(tool: str, args: dict) -> dict:
    if tool not in _DISPATCH:
        raise KeyError(tool)
    return _DISPATCH[tool](args)
