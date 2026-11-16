# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Unity Catalog setup
# MAGIC Creates the schemas, volumes and Delta tables, seeds curated reference data and evaluation
# MAGIC cases, and grants the app's service principal what it needs. Safe to re-run (idempotent).
# MAGIC
# MAGIC Run as a user with `CREATE CATALOG` (or an existing catalog you own).

# COMMAND ----------

dbutils.widgets.text("catalog", "prior_auth")
dbutils.widgets.text("schema", "core")
dbutils.widgets.text("app_sp", "", "App service principal application id (optional)")
dbutils.widgets.text("reviewers_group", "", "Group of clinical reviewers (optional)")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
app_sp = dbutils.widgets.get("app_sp").strip()
reviewers = dbutils.widgets.get("reviewers_group").strip()

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS `{catalog}`")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}` COMMENT 'Prior authorization review: core data'")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`tools` COMMENT 'Unity Gateway MCP services and connections'")
for vol, comment in [("raw_documents", "Uploaded referrals, notes, labs, imaging reports"),
                     ("generated_reports", "Audit justification PDFs and decision letters")]:
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{vol}` COMMENT '{comment}'")

# COMMAND ----------

import os

# Notebooks run with the notebook's folder as working directory (Git folder or bundle).
ddl = open(os.path.abspath("../sql/ddl_delta.sql")).read()
ddl = ddl.replace("${catalog}", f"`{catalog}`").replace("${schema}", f"`{schema}`")
for stmt in ddl.split(";"):
    body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if body:
        spark.sql(body)
print("Tables:", [r.tableName for r in spark.sql(f"SHOW TABLES IN `{catalog}`.`{schema}`").collect()])

# COMMAND ----------

# MAGIC %md ### Seed curated CPT list (from the Microsoft pre-flight table) and evaluation cases

# COMMAND ----------

import importlib.util, json, datetime as dt

spec = importlib.util.spec_from_file_location("cptv", os.path.abspath("../app/app/services/cpt_validation.py"))
cptv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cptv)
table = cptv._KNOWN_CODES
rows = [(code, info.get("description", ""), info.get("category", ""), dt.datetime.utcnow())
        for code, info in table.items() if isinstance(info, dict)]
spark.createDataFrame(rows, "code string, description string, category string, loaded_at timestamp") \
    .write.mode("overwrite").saveAsTable(f"`{catalog}`.`{schema}`.ref_cpt_common")
print(f"ref_cpt_common: {len(rows)} codes")

# COMMAND ----------

seed = json.load(open(os.path.abspath("../../tests/eval_cases.json")))
existing = {r.case_id for r in spark.table(f"`{catalog}`.`{schema}`.eval_cases").select("case_id").collect()}
new = [(c["case_id"], json.dumps(c["request"]), c["expected_recommendation"], c.get("expected_gate"), "seed",
        dt.datetime.utcnow()) for c in seed if c["case_id"] not in existing]
if new:
    spark.createDataFrame(new, "case_id string, request_json string, expected_recommendation string, "
                               "expected_gate string, source string, added_at timestamp") \
        .selectExpr("case_id", "parse_json(request_json) AS request_json", "expected_recommendation",
                    "expected_gate", "source", "added_at") \
        .write.mode("append").saveAsTable(f"`{catalog}`.`{schema}`.eval_cases")
print(f"eval_cases: added {len(new)}")

# COMMAND ----------

# MAGIC %md ### Grants

# COMMAND ----------

def grant(stmt):
    try:
        spark.sql(stmt)
        print("OK  ", stmt)
    except Exception as e:
        print("SKIP", stmt, "->", str(e)[:120])

if app_sp:
    p = f"`{app_sp}`"
    grant(f"GRANT USE CATALOG ON CATALOG `{catalog}` TO {p}")
    grant(f"GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA `{catalog}`.`{schema}` TO {p}")
    grant(f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`{schema}`.raw_documents TO {p}")
    grant(f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`{schema}`.generated_reports TO {p}")
    grant(f"GRANT USE SCHEMA, EXECUTE ON SCHEMA `{catalog}`.`tools` TO {p}")
if reviewers:
    g = f"`{reviewers}`"
    grant(f"GRANT USE CATALOG ON CATALOG `{catalog}` TO {g}")
    grant(f"GRANT USE SCHEMA, SELECT ON SCHEMA `{catalog}`.`{schema}` TO {g}")
