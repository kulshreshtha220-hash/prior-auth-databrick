"""Runs one specialist agent: tool-calling loop + structured JSON output.

Shared by the MLflow ResponsesAgent (Model Serving) and by the app's
in-process mode, so both behave identically.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from pydantic import ValidationError

from .config import AGENT_MAX_TURNS, get_settings
from .llm import openai_client
from .mcp_tools import Toolbox
from .prompts import system_prompt
from .schemas import AGENT_SCHEMAS

logger = logging.getLogger(__name__)

try:  # tracing is optional (no-op outside Databricks)
    import mlflow

    _trace = mlflow.trace
except Exception:  # noqa: BLE001
    def _trace(*a, **k):  # type: ignore[no-redef]
        def deco(f):
            return f
        return deco(a[0]) if a and callable(a[0]) else deco


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


def _extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def _validate(agent_key: str, data: dict) -> tuple[dict, str | None]:
    schema = AGENT_SCHEMAS[agent_key]
    try:
        return schema.model_validate(data).model_dump(), None
    except ValidationError as e:
        # Keep everything that is valid: whole fields, and for lists the individual valid items,
        # so one malformed entry never drops a whole list (e.g. diagnosis_validation).
        logger.warning("%s output failed validation: %s", agent_key, e)
        clean = {}
        for k, v in data.items():
            if k not in schema.model_fields:
                continue
            try:
                schema.model_validate({k: v})
                clean[k] = v
            except ValidationError:
                if isinstance(v, dict):
                    # nested object (e.g. clinical_extraction): keep its valid sub-fields
                    sub = {}
                    for sk, sv in v.items():
                        try:
                            schema.model_validate({k: {sk: sv}})
                            sub[sk] = sv
                        except ValidationError:
                            pass
                    if sub:
                        clean[k] = sub
                elif isinstance(v, list):
                    kept = []
                    for item in v:
                        try:
                            schema.model_validate({k: [item]})
                            kept.append(item)
                        except ValidationError:
                            pass
                    if kept:
                        clean[k] = kept
        return schema.model_validate(clean).model_dump(), str(e)[:500]


def _structured_call(client, model: str, messages: list[dict], agent_key: str) -> str | None:
    schema = AGENT_SCHEMAS[agent_key].model_json_schema()
    s = get_settings()
    attempts = [
        {"type": "json_schema", "json_schema": {"name": f"{agent_key}_result", "schema": schema, "strict": False}},
        {"type": "json_object"},
        None,
    ]
    ask = {
        "role": "user",
        "content": "Return the final result now as one JSON object that matches this JSON schema. "
        "Output JSON only.\n" + json.dumps(schema)[:12000],
    }
    for rf in attempts:
        try:
            kwargs: dict[str, Any] = dict(model=model, messages=messages + [ask], temperature=s.llm_temperature,
                                          max_tokens=s.llm_max_tokens)
            if rf:
                kwargs["response_format"] = rf
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001 - model may not support this response_format
            logger.info("structured call with %s failed: %s", rf and rf["type"], str(e)[:200])
    return None


@_trace(name="run_agent", span_type="AGENT")
def run_agent(agent_key: str, payload: dict) -> dict:
    """Run `agent_key` on `payload` and return its validated result dict."""
    s = get_settings()
    model = s.model_for(agent_key)
    started = time.time()
    toolbox = Toolbox.for_agent(agent_key)
    sys_text, prompt_source = system_prompt(agent_key)
    note = toolbox.availability_note()
    if note:
        sys_text += "\n\n" + note

    messages: list[dict] = [
        {"role": "system", "content": sys_text},
        {"role": "user", "content": json.dumps(payload, default=str)},
    ]
    tools = toolbox.openai_tools()
    final_text: str | None = None
    turns = 0
    error: str | None = None
    try:
        client = openai_client(model)
        for turns in range(1, AGENT_MAX_TURNS[agent_key] + 1):
            kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=s.llm_temperature,
                                          max_tokens=s.llm_max_tokens)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            msg = client.chat.completions.create(**kwargs).choices[0].message
            if getattr(msg, "tool_calls", None):
                messages.append(msg.model_dump(exclude_none=True))
                for tc in msg.tool_calls:
                    out = toolbox.call(tc.function.name, tc.function.arguments)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
                continue
            final_text = msg.content
            messages.append({"role": "assistant", "content": final_text or ""})
            break
        data = _extract_json(final_text)
        if data is None:
            data = _extract_json(_structured_call(client, model, messages, agent_key))
        if data is None:
            raise ValueError("model did not return parseable JSON")
        result, validation_issue = _validate(agent_key, data)
        # `error` is reserved for real runtime failures. If the model wrote a note there
        # (e.g. "one PubMed search failed"), keep it as a warning, not an agent error.
        model_note = result.get("error") if "error" in result else None
        if model_note:
            result["error"] = None
            if "tool_results" in result:
                result["tool_results"].append({"tool_name": "agent_note", "status": "warning", "detail": str(model_note)[:500]})
    except Exception as e:  # noqa: BLE001
        logger.exception("Agent %s failed", agent_key)
        error = f"{type(e).__name__}: {str(e)[:500]}"
        result = AGENT_SCHEMAS[agent_key]().model_dump()
        result["error"] = error if "error" in result else None
        validation_issue = None

    # Make every UNKNOWN tool call visible in tool_results (never silently dropped).
    if "tool_results" in result:
        for c in toolbox.calls:
            if c.status == "UNKNOWN":
                result["tool_results"].append(
                    {"tool_name": f"{c.server}:{c.tool}", "status": "warning", "detail": f"UNKNOWN - {c.detail}"}
                )
        for srv, why in toolbox.unavailable.items():
            result["tool_results"].append(
                {"tool_name": srv, "status": "warning", "detail": f"UNKNOWN - source unavailable: {why}"}
            )
    if error and "error" not in result:
        result["_error"] = error

    result["_meta"] = {
        "agent": agent_key,
        "model": model,
        "prompt": prompt_source,
        "turns": turns,
        "duration_s": round(time.time() - started, 2),
        "tool_calls": [c.__dict__ for c in toolbox.calls],
        "unavailable_sources": toolbox.unavailable,
        "validation_issue": validation_issue,
    }
    return result
