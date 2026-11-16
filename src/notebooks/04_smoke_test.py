# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Smoke test the four agent endpoints with the sample case
# MAGIC Waits until each endpoint is READY, sends the Microsoft sample case (CT-guided lung biopsy),
# MAGIC and checks that each agent returns valid JSON for its schema. Then runs the deterministic
# MAGIC gates on the three specialist outputs. Fails the job if anything is broken.

# COMMAND ----------

# MAGIC %pip install -q "databricks-sdk>=0.60" "pydantic>=2.7"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("endpoint_prefix", "pa")
dbutils.widgets.text("timeout_min", "40")
prefix, timeout_min = dbutils.widgets.get("endpoint_prefix"), int(dbutils.widgets.get("timeout_min"))

# COMMAND ----------

import json, os, sys, time
from databricks.sdk import WorkspaceClient

sys.path.insert(0, os.path.abspath("../app"))
from pa_core import gates  # noqa: E402
from pa_core.schemas import AGENT_SCHEMAS  # noqa: E402

w = WorkspaceClient()
case = json.load(open(os.path.abspath("../../tests/eval_cases.json")))[0]["request"]

def wait_ready(name):
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        ep = w.serving_endpoints.get(name)
        ready = str(ep.state.ready) if ep.state else ""
        updating = str(ep.state.config_update) if ep.state else ""
        if "READY" in ready and "IN_PROGRESS" not in updating:
            return
        print(f"  waiting for {name}: {ready} / {updating}")
        time.sleep(30)
    raise TimeoutError(f"{name} not ready after {timeout_min} min")

def call(agent, payload):
    name = f"{prefix}-{agent}-agent"
    wait_ready(name)
    t = time.time()
    raw = w.api_client.do("POST", f"/serving-endpoints/{name}/invocations",
                          body={"input": [{"role": "user", "content": json.dumps(payload)}]})
    text = next(b["text"] for item in raw["output"] for b in item.get("content", []) if "text" in b)
    out = json.loads(text)
    AGENT_SCHEMAS[agent].model_validate({k: v for k, v in out.items() if not k.startswith("_")})
    err = out.get("error") or out.get("_error")
    meta = out.get("_meta", {})
    print(f"{agent:11s} {time.time()-t:6.1f}s model={meta.get('model')} prompt={meta.get('prompt')} "
          f"tools={len(meta.get('tool_calls', []))} unavailable={list(meta.get('unavailable_sources', {}))} error={err}")
    if err:
        raise RuntimeError(f"{agent} returned error: {err}")
    return out

# COMMAND ----------

compliance = call("compliance", case)
clinical = call("clinical", {**case, "cpt_preflight": {"valid": True, "summary": "1/1 codes valid format"}})
coverage = call("coverage", {"request": case, "clinical_findings": {k: v for k, v in clinical.items() if k != "_meta"}})
outcome = gates.evaluate(compliance, clinical, coverage, {"valid": True, "summary": "1/1"}).to_dict()
synthesis = call("synthesis", {"request": case, "compliance_result": compliance, "clinical_result": clinical,
                               "coverage_result": coverage, "deterministic_gates": outcome})
print("\nGates:", outcome["recommendation"], outcome["decision_gate"], outcome["confidence"], outcome["confidence_level"])
print("Gate reasons:", json.dumps(outcome["gate_reasons"], indent=1))
print("Synthesis summary:", synthesis.get("summary"))
