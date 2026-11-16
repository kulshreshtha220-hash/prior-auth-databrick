"""The MLflow ResponsesAgent wrapper parses the JSON payload and returns the result as one text item."""
import importlib.util
import json
from pathlib import Path

from mlflow.types.responses import ResponsesAgentRequest


def test_responses_agent_roundtrip(monkeypatch):
    monkeypatch.setenv("PA_AGENT_KEY", "compliance")
    path = Path(__file__).resolve().parents[1] / "src" / "agents" / "agent.py"
    spec = importlib.util.spec_from_file_location("pa_agent_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = {}

    def fake_run(agent_key, payload):
        seen.update(agent=agent_key, payload=payload)
        return {"checklist": [], "overall_status": "complete", "_meta": {"agent": agent_key}}

    monkeypatch.setattr(mod, "run_agent", fake_run)
    req = ResponsesAgentRequest(input=[{"role": "user", "content": json.dumps({"patient_name": "A"})}])
    resp = mod.PriorAuthAgent().predict(req)
    assert seen == {"agent": "compliance", "payload": {"patient_name": "A"}}
    item = resp.output[0].model_dump() if hasattr(resp.output[0], "model_dump") else resp.output[0]
    text = item["content"][0]["text"]
    assert json.loads(text)["overall_status"] == "complete"
    # app-side parser understands the endpoint's output shape
    from app.services.agent_client import _parse_responses_output
    assert _parse_responses_output(resp.model_dump())["overall_status"] == "complete"
