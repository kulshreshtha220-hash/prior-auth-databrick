# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Pick the LLM for the agents
# MAGIC Lists the chat models this workspace can use (Unity Gateway model services in `system.ai`, and
# MAGIC pay-per-token serving endpoints) and picks the best one by preference. Re-run any time; the
# MAGIC result is returned as a task value `llm_model` and printed so you can paste it into
# MAGIC `databricks.yml` (`llm_model` variable).

# COMMAND ----------

dbutils.widgets.text("preferred", "claude-sonnet-4-6,claude-sonnet-4-5,claude-opus-4-6,claude-opus-4-5,claude-sonnet-4,claude-3-7-sonnet,gpt-5,gpt-5-1,llama-4-maverick,meta-llama-3-3-70b-instruct", "Preference order")
preferred = [p.strip() for p in dbutils.widgets.get("preferred").split(",") if p.strip()]

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
candidates = {}

# 1) Unity Gateway model services (system.ai.<model>)
try:
    resp = w.api_client.do("GET", "/api/2.0/ai-gateway/model-services", query={"parent": "schemas/system.ai"})
    for svc in resp.get("model_services", resp.get("services", [])) or []:
        name = svc.get("name", "").replace("model-services/", "")
        if name:
            candidates[name.split(".")[-1]] = name
except Exception as e:  # API shape differs by release; fall back to the CLI listing in the runbook
    print("Model services listing unavailable:", str(e)[:200])

# 2) Pay-per-token / chat serving endpoints (databricks-<model>)
for ep in w.serving_endpoints.list():
    task = (ep.task or "")
    if ep.name.startswith("databricks-") and ("chat" in task or "llm" in task or not task):
        candidates.setdefault(ep.name.removeprefix("databricks-"), ep.name)

print("Available chat models:")
for k, v in sorted(candidates.items()):
    print(f"  {k:40s} -> {v}")

# COMMAND ----------

chosen = next((candidates[p] for p in preferred if p in candidates), None)
if chosen is None:
    raise ValueError("None of the preferred models is available. Pick one from the list above and set var llm_model.")
print(f"\nSELECTED llm_model = {chosen}")
dbutils.jobs.taskValues.set(key="llm_model", value=chosen)
dbutils.notebook.exit(chosen)
