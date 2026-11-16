"""Dispatch to the four specialist agents (replaces Microsoft's hosted_agents.py).

Modes (PA_AGENT_MODE):
  endpoint  - POST to the agent's Model Serving endpoint (production)
  inprocess - run pa_core.agent_runtime inside the app (dev / small workspaces)
  mock      - canned results, no LLM or tools (UI and pipeline tests)

Each mode returns the agent's result dict, or {"error": ...}; it never raises,
so one failing agent becomes a PEND, not a crashed review.
"""
from __future__ import annotations

import asyncio
import json
import logging

from pa_core.config import get_settings

logger = logging.getLogger(__name__)


def _parse_responses_output(data: dict) -> dict:
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") in ("output_text", "text"):
                try:
                    return json.loads(block.get("text", ""))
                except json.JSONDecodeError:
                    return {"error": f"Agent returned non-JSON text: {block.get('text', '')[:200]}"}
    return {"error": f"Unexpected agent response shape: {str(data)[:300]}"}


def _call_endpoint(agent_key: str, payload: dict) -> dict:
    from pa_core.llm import workspace_client

    s = get_settings()
    w = workspace_client()
    body = {"input": [{"role": "user", "content": json.dumps(payload, default=str)}]}
    raw = w.api_client.do(
        "POST",
        f"/serving-endpoints/{s.endpoint_for(agent_key)}/invocations",
        body=body,
    )
    return _parse_responses_output(raw if isinstance(raw, dict) else json.loads(raw))


def _call_inprocess(agent_key: str, payload: dict) -> dict:
    from pa_core.agent_runtime import run_agent

    return run_agent(agent_key, payload)


async def invoke_agent(agent_key: str, payload: dict) -> dict:
    s = get_settings()
    try:
        if s.agent_mode == "mock":
            from app.services.mock_agents import mock_result

            await asyncio.sleep(0.4)
            return mock_result(agent_key, payload)
        fn = _call_inprocess if s.agent_mode == "inprocess" else _call_endpoint
        return await asyncio.wait_for(asyncio.to_thread(fn, agent_key, payload), timeout=s.agent_timeout_s)
    except asyncio.TimeoutError:
        return {"error": f"{agent_key} agent timed out after {s.agent_timeout_s:.0f}s", "tool_results": []}
    except Exception as e:  # noqa: BLE001
        logger.exception("Agent %s call failed", agent_key)
        return {"error": f"{type(e).__name__}: {str(e)[:400]}", "tool_results": []}
