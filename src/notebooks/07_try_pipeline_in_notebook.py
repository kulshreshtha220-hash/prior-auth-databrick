# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Try the full review inside this notebook (no deployment needed)
# MAGIC Runs the real pipeline (4 agents with the real LLM + live MCP tools + Python gates) **inside this
# MAGIC notebook** on Serverless, using the sample case. No serving endpoints, app, Lakebase or SQL
# MAGIC warehouse needed. Use it to prove the model and MCP access work before deploying anything.
# MAGIC
# MAGIC Takes 1–4 minutes. Prints progress, the gate outcome, and what each agent found.

# COMMAND ----------

# MAGIC %pip install -q -r ../app/requirements.txt
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("llm_model", "auto", "LLM: auto | system.ai.<model> | databricks-<model>")
dbutils.widgets.dropdown("mcp_mode", "direct", ["direct", "service", "off"], "MCP mode")
dbutils.widgets.dropdown("case", "seed-001-lung-biopsy", ["seed-001-lung-biopsy", "seed-002-invalid-icd", "seed-003-thin-notes", "seed-004-bad-npi"])

# COMMAND ----------

# MAGIC %md ### 1. Which chat models can this workspace use?

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
endpoints = sorted(e.name for e in w.serving_endpoints.list() if e.name.startswith("databricks-"))
print("Pay-per-token endpoints visible to you:")
for n in endpoints:
    print("  ", n)

PREFERRED = ["claude-sonnet-4-6", "claude-sonnet-4-5", "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-4",
             "claude-3-7-sonnet", "gpt-5", "gpt-5-1", "llama-4-maverick", "meta-llama-3-3-70b-instruct"]
model = dbutils.widgets.get("llm_model").strip()
if model == "auto":
    model = next((f"databricks-{p}" for p in PREFERRED if f"databricks-{p}" in endpoints), None)
    if model is None:
        raise ValueError("No preferred chat model found. Set the llm_model widget to one from the list above "
                         "(or system.ai.<model> if your workspace uses Unity Gateway model services).")
print("\nUsing model:", model)

# COMMAND ----------

# MAGIC %md ### 2. Quick model check (one short call)

# COMMAND ----------

import os, sys
os.environ.update({
    "PA_LLM_MODEL": model, "PA_MCP_MODE": dbutils.widgets.get("mcp_mode"),
    "PA_AGENT_MODE": "inprocess", "PA_STATE_STORE": "memory", "PA_WRITE_DELTA": "false",
    "PA_USE_PROMPT_REGISTRY": "false", "PA_REFERENCE_FALLBACK": "false", "MLFLOW_DISABLE_AGENT_HINT": "1",
})
sys.path.insert(0, os.path.abspath("../app"))
from pa_core.llm import openai_client  # noqa: E402

r = openai_client(model).chat.completions.create(
    model=model, messages=[{"role": "user", "content": "Reply with exactly: model ok"}], max_tokens=10)
print(r.choices[0].message.content)

# COMMAND ----------

# MAGIC %md ### 3. Quick MCP check (lists the tools of each healthcare server)

# COMMAND ----------

from pa_core.mcp_tools import Toolbox

for agent in ("clinical", "coverage"):
    box = Toolbox.for_agent(agent)
    print(f"{agent}: {len(box.tools)} tools; unavailable: {box.unavailable or 'none'}")
    print("   ", ", ".join(t.name for t in box.tools)[:400])

# COMMAND ----------

# MAGIC %md ### 4. Run the full review on the sample case

# COMMAND ----------

import asyncio, concurrent.futures, json, time

case_id = dbutils.widgets.get("case")
case = next(c for c in json.load(open(os.path.abspath("../../tests/eval_cases.json"))) if c["case_id"] == case_id)
print(f"Case {case_id}: {case['description']}  (expected: {case['expected_recommendation']} / {case['expected_gate']})\n")

from app.agents.orchestrator import run_multi_agent_review  # noqa: E402

t0 = time.time()

async def progress(ev):
    agents = ", ".join(f"{k}={v.get('status')}" for k, v in (ev.get("agents") or {}).items())
    print(f"[{time.time() - t0:6.1f}s] {ev.get('progress_pct', 0):3d}%  {ev.get('message', '')}  {agents}")

with concurrent.futures.ThreadPoolExecutor(1) as ex:
    result = ex.submit(asyncio.run, run_multi_agent_review(case["request"], on_progress=progress)).result()

# COMMAND ----------

# MAGIC %md ### 5. Result

# COMMAND ----------

trail = result.get("synthesis_audit_trail") or {}
print("RECOMMENDATION :", result["recommendation"], f"(expected {case['expected_recommendation']})")
print("DECISION GATE  :", result["decision_gate"], f"(expected {case['expected_gate']})")
print("CONFIDENCE     :", result["confidence"], result["confidence_level"])
print("GATE RESULTS   :", json.dumps(trail.get("gate_results"), indent=1))
print("GATE REASONS   :", json.dumps(trail.get("gate_reasons"), indent=1))
print("\nSUMMARY:", result.get("summary"))
print("\nTOOLS USED:")
for t in result["tool_results"]:
    print(f"  {t['status']:8s} {t['tool_name']}: {str(t['detail'])[:120]}")
for name, r in result["agent_results"].items():
    err = r.get("error")
    print(f"\n{name.upper()} error={err}")
    print("  ", json.dumps({k: v for k, v in r.items() if k not in ('checks_performed', 'tool_results')}, default=str)[:800])
