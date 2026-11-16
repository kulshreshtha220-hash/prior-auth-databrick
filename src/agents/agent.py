"""MLflow ResponsesAgent for one prior-authorization specialist agent.

One code file serves all four agents. `log_and_deploy_agents` logs it four
times with a different `model_config` (agent_key + runtime settings), so
each agent is its own UC model and its own Model Serving endpoint, like the
four Foundry hosted agents in the Microsoft design.

Request:  {"input": [{"role": "user", "content": "<JSON case payload>"}]}
Response: one text output item whose text is the agent's JSON result.
"""
import json
import os
import uuid
from typing import Generator

import mlflow
from mlflow.models import ModelConfig
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

_cfg = ModelConfig(development_config={"agent_key": os.environ.get("PA_AGENT_KEY", "compliance"), "env": {}})
AGENT_KEY = _cfg.get("agent_key")
# Runtime settings travel inside the model config so the endpoint needs no
# extra environment setup. Explicit endpoint env vars still win.
for _k, _v in (_cfg.get("env") or {}).items():
    os.environ.setdefault(_k, str(_v))

from pa_core.agent_runtime import run_agent  # noqa: E402  (after env is set)


def _payload_from_request(request: ResponsesAgentRequest) -> dict:
    text = ""
    for item in reversed(request.input):
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        if d.get("role") == "user":
            content = d.get("content")
            if isinstance(content, list):
                text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            else:
                text = str(content or "")
            break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"request": {"clinical_notes": text}}


class PriorAuthAgent(ResponsesAgent):
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        result = run_agent(AGENT_KEY, _payload_from_request(request))
        item = self.create_text_output_item(text=json.dumps(result, default=str), id=f"msg_{uuid.uuid4().hex[:12]}")
        return ResponsesAgentResponse(output=[item], custom_outputs={"agent": AGENT_KEY, "meta": result.get("_meta", {})})

    def predict_stream(self, request: ResponsesAgentRequest) -> Generator[ResponsesAgentStreamEvent, None, None]:
        resp = self.predict(request)
        for item in resp.output:
            yield ResponsesAgentStreamEvent(type="response.output_item.done", item=item)


mlflow.openai.autolog()
mlflow.models.set_model(PriorAuthAgent())
