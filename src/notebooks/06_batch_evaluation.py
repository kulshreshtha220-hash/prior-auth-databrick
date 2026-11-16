# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Batch evaluation (job: `pa_batch_evaluation`, nightly and after prompt changes)
# MAGIC Runs the full review pipeline (same LangGraph code as the app, against the deployed agent
# MAGIC endpoints) on the labelled cases in `eval_cases`, scores it with MLflow 3 GenAI evaluation,
# MAGIC and fails the job if recommendation accuracy drops below the threshold.
# MAGIC
# MAGIC Reviewer overrides from `final_decisions` are added to `eval_cases` automatically, so every
# MAGIC human correction becomes a regression test (diagram: "scorers, reviewer feedback, labelled sets").

# COMMAND ----------

# MAGIC %pip install -q -r ../app/requirements.txt
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "prior_auth")
dbutils.widgets.text("schema", "core")
dbutils.widgets.text("endpoint_prefix", "pa")
dbutils.widgets.text("min_accuracy", "0.75")
dbutils.widgets.text("max_cases", "200")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
T = lambda t: f"`{catalog}`.`{schema}`.`{t}`"  # noqa: E731

# COMMAND ----------

# Add reviewer overrides as new labelled cases (expected = what the human decided)
spark.sql(f"""
INSERT INTO {T('eval_cases')}
SELECT concat('override-', d.request_id), r.request_json, d.final_recommendation, NULL, 'reviewer_override', current_timestamp()
FROM {T('final_decisions')} d JOIN {T('pa_requests')} r ON r.request_id = d.request_id
WHERE d.was_overridden AND NOT EXISTS (SELECT 1 FROM {T('eval_cases')} e WHERE e.case_id = concat('override-', d.request_id))
""")
cases = spark.sql(f"SELECT case_id, to_json(request_json) AS req, expected_recommendation, expected_gate, source "
                  f"FROM {T('eval_cases')} ORDER BY added_at DESC LIMIT {int(dbutils.widgets.get('max_cases'))}").collect()
print(f"{len(cases)} evaluation cases")

# COMMAND ----------

import asyncio, json, os, sys

os.environ.update({
    "PA_CATALOG": catalog, "PA_SCHEMA": schema, "PA_AGENT_MODE": "endpoint",
    "PA_AGENT_ENDPOINT_PREFIX": dbutils.widgets.get("endpoint_prefix"),
    "PA_STATE_STORE": "memory", "PA_WRITE_DELTA": "false", "MLFLOW_DISABLE_AGENT_HINT": "1",
})
sys.path.insert(0, os.path.abspath("../app"))
from app.agents.orchestrator import run_multi_agent_review  # noqa: E402

import mlflow
from mlflow.genai.scorers import Guidelines, scorer

user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/prior-auth-evaluation")

import concurrent.futures

def predict_fn(request: dict) -> dict:
    # Notebooks already run an event loop; run each review in its own thread + loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        out = ex.submit(asyncio.run, run_multi_agent_review(request)).result()
    return {k: out.get(k) for k in ("recommendation", "decision_gate", "confidence", "confidence_level", "summary",
                                    "clinical_rationale", "disclaimer", "synthesis_audit_trail")}

# COMMAND ----------

@scorer
def recommendation_match(outputs, expectations) -> bool:
    return outputs.get("recommendation") == expectations.get("expected_recommendation")

@scorer
def gate_match(outputs, expectations):
    exp = expectations.get("expected_gate")
    return None if not exp else outputs.get("decision_gate") == exp

@scorer
def never_deny(outputs) -> bool:
    return outputs.get("recommendation") in ("approve", "pend_for_review")

@scorer
def disclaimer_present(outputs) -> bool:
    return bool(outputs.get("disclaimer"))

grounded = Guidelines(
    name="grounded_rationale",
    guidelines=[
        "The clinical_rationale must explain the outcome using findings attributed to the Compliance, Clinical "
        "Reviewer or Coverage agents, and must not invent clinical facts that are not in the request.",
        "If the recommendation is pend_for_review, the rationale must say what documentation or verification is needed.",
    ],
)

data = [{
    "inputs": {"request": json.loads(c.req)},
    "expectations": {"expected_recommendation": c.expected_recommendation, "expected_gate": c.expected_gate},
    "tags": {"case_id": c.case_id, "source": c.source},
} for c in cases]

result = mlflow.genai.evaluate(data=data, predict_fn=predict_fn,
                               scorers=[recommendation_match, gate_match, never_deny, disclaimer_present, grounded])
print(json.dumps(result.metrics, indent=2, default=str))

# COMMAND ----------

acc_key = next((k for k in result.metrics if k.startswith("recommendation_match") and "mean" in k), None)
accuracy = float(result.metrics.get(acc_key, 0)) if acc_key else 0.0
deny_key = next((k for k in result.metrics if k.startswith("never_deny") and "mean" in k), None)
min_acc = float(dbutils.widgets.get("min_accuracy"))
print(f"recommendation accuracy = {accuracy:.2%} (threshold {min_acc:.0%})")
if deny_key and float(result.metrics[deny_key]) < 1.0:
    raise RuntimeError("A DENY recommendation was produced: this must never happen")
if accuracy < min_acc:
    raise RuntimeError(f"Accuracy {accuracy:.2%} below threshold {min_acc:.0%}: do not promote new prompts or models")
dbutils.notebook.exit(json.dumps({"accuracy": accuracy, "cases": len(data), "run_id": result.run_id}))
