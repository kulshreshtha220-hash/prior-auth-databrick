"""MCP client layer (diagram: "MCP client layer: custom MCP servers on Apps,
UC connections").

Each agent gets a toolbox limited to its allow-listed servers. Three sources,
tried in this order:

1. Live MCP server
   * ``service`` mode: Unity Gateway MCP service
     ``https://<host>/ai-gateway/mcp-services/<catalog>.<schema>.<server>``
   * ``direct`` mode: the public Anthropic URL (local dev / fallback)
2. Reference adapter: versioned Delta snapshot (see reference.py)
3. Nothing: the agent is told the tool is unavailable.

Hard rule from the design: a tool that fails or is unreachable returns
status ``UNKNOWN``. It never produces an automatic failure or denial; the
gates turn UNKNOWN into PEND for manual review.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from . import reference, sql
from .config import AGENT_MCP_SERVERS, MCP_PUBLIC_URLS, get_settings

logger = logging.getLogger(__name__)

USER_AGENT = "pa-review-databricks/1.0"  # Cloudflare in front of hcls.mcp.claude.com rejects Python-urllib
_MAX_RESULT_CHARS = 12000


@dataclass
class ToolSpec:
    server: str
    name: str  # name on the server
    description: str
    parameters: dict
    source: str  # "mcp" | "reference"

    @property
    def fn_name(self) -> str:
        # OpenAI function names: [a-zA-Z0-9_-]{1,64}
        return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{self.server}__{self.name}")[:64]


@dataclass
class ToolCallRecord:
    tool: str
    server: str
    status: str  # OK | UNKNOWN | ERROR
    detail: str
    source: str


def unknown(reason: str) -> dict:
    return {
        "status": "UNKNOWN",
        "reason": reason,
        "instruction": "Treat this check as UNKNOWN. Do not fail, deny or guess; flag it for manual review.",
    }


def _run_async(coro):
    """Run a coroutine from sync code, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _result_to_payload(res: Any) -> dict:
    if getattr(res, "isError", False):
        text = " ".join(getattr(c, "text", "") for c in (res.content or []))
        return unknown(f"tool returned an error: {text[:500]}")
    structured = getattr(res, "structuredContent", None)
    if structured:
        return {"status": "OK", "data": structured}
    texts = [getattr(c, "text", "") for c in (getattr(res, "content", None) or [])]
    joined = "\n".join(t for t in texts if t)
    try:
        return {"status": "OK", "data": json.loads(joined)}
    except (json.JSONDecodeError, TypeError):
        return {"status": "OK", "data": joined}


class _DirectServer:
    """Streamable-HTTP MCP client against a public URL."""

    def __init__(self, url: str, timeout: float):
        self.url, self.timeout = url, timeout

    async def _session(self, fn):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(self.url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await fn(s)

    def list_tools(self):
        return _run_async(self._session(lambda s: s.list_tools())).tools

    def call_tool(self, name: str, args: dict):
        return _run_async(self._session(lambda s: s.call_tool(name, args)))


class _ServiceServer:
    """Unity Gateway MCP service via the Databricks MCP client."""

    def __init__(self, full_name: str):
        from databricks_mcp import DatabricksMCPClient

        from .llm import workspace_client

        w = workspace_client()
        url = f"{w.config.host.rstrip('/')}/ai-gateway/mcp-services/{full_name}"
        self.client = DatabricksMCPClient(server_url=url, workspace_client=w)

    def list_tools(self):
        return self.client.list_tools()

    def call_tool(self, name: str, args: dict):
        return self.client.call_tool(name, args)


@dataclass
class Toolbox:
    agent_key: str
    tools: list[ToolSpec] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)  # server -> reason
    calls: list[ToolCallRecord] = field(default_factory=list)
    _servers: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- build
    @classmethod
    def for_agent(cls, agent_key: str) -> "Toolbox":
        s = get_settings()
        box = cls(agent_key)
        for server in AGENT_MCP_SERVERS.get(agent_key, ()):
            mode = s.source_mode(server)
            if mode == "off":
                box.unavailable[server] = "source disabled (PA_DATA_SOURCES / PA_MCP_MODE=off)"
                continue
            if mode == "uc":
                if server not in reference.ADAPTER_TOOLS:
                    box.unavailable[server] = "no Unity Catalog adapter for this source"
                elif not sql.available():
                    box.unavailable[server] = "Unity Catalog source needs a SQL warehouse (DATABRICKS_WAREHOUSE_ID)"
                else:
                    box._add_reference_tools(server)
                continue
            try:
                if s.mcp_mode == "direct":
                    srv = _DirectServer(MCP_PUBLIC_URLS[server], s.mcp_timeout_s)
                else:
                    srv = _ServiceServer(f"{s.mcp_schema}.{server}")
                listed = srv.list_tools()
                box._servers[server] = srv
                for t in listed:
                    box.tools.append(ToolSpec(
                        server=server,
                        name=t.name,
                        description=(t.description or "")[:1000],
                        parameters=getattr(t, "inputSchema", None) or {"type": "object", "properties": {}},
                        source="mcp",
                    ))
                continue
            except Exception as e:  # noqa: BLE001 - any failure means "unavailable"
                logger.warning("MCP server %s unavailable: %s", server, e)
                box.unavailable[server] = f"{type(e).__name__}: {str(e)[:200]}"
            # adapter fallback when the live server is down
            if s.reference_fallback and sql.available() and server in reference.ADAPTER_TOOLS:
                box._add_reference_tools(server)
        return box

    def _add_reference_tools(self, server: str) -> None:
        for t in reference.ADAPTER_TOOLS[server]:
            self.tools.append(ToolSpec(server, t["name"], t["description"], t["parameters"], "reference"))

    # ---------------------------------------------------------------- use
    def openai_tools(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t.fn_name, "description": t.description, "parameters": t.parameters}}
            for t in self.tools
        ]

    def availability_note(self) -> str:
        parts = []
        uc = sorted({t.server for t in self.tools if t.source == "reference"})
        if uc:
            mapping = "\n".join(f"- {srv}: {reference.SKILL_TOOL_MAP.get(srv, '')}" for srv in uc)
            parts.append(
                "DATA SOURCES FOR THIS DEPLOYMENT\n"
                "These sources are served from Unity Catalog reference tables instead of the MCP tools named in the "
                "skill. Use the Unity Catalog tool wherever the skill names the MCP tool:\n" + mapping +
                "\nTheir results are authoritative. In tool_results, name the tool you actually called."
            )
        if self.unavailable:
            lines = "\n".join(f"- {srv}: {why}" for srv, why in self.unavailable.items())
            parts.append(
                "TOOL AVAILABILITY NOTICE\nThese data sources are unavailable for this run:\n" + lines +
                "\nFor any check that depends on them, report status UNKNOWN (tool_results status 'warning'), "
                "state that manual verification is required, and never mark the item as failed or invalid "
                "because the tool was missing. PubMed and Clinical Trials are supplementary: skip them quietly."
            )
        return "\n\n".join(parts)

    def call(self, fn_name: str, args_json: str | dict) -> str:
        spec = next((t for t in self.tools if t.fn_name == fn_name), None)
        if spec is None:
            payload = unknown(f"unknown tool {fn_name}")
            self.calls.append(ToolCallRecord(fn_name, "?", "UNKNOWN", payload["reason"], "none"))
            return json.dumps(payload)
        try:
            args = json.loads(args_json) if isinstance(args_json, str) else dict(args_json or {})
        except json.JSONDecodeError:
            args = {}
        try:
            if spec.source == "reference":
                payload = {"status": "OK", "source": "reference_snapshot", "data": reference.call(spec.name, args)}
            else:
                try:
                    raw = self._servers[spec.server].call_tool(spec.name, args)
                except Exception:  # noqa: BLE001 - retry once, then report UNKNOWN below
                    raw = self._servers[spec.server].call_tool(spec.name, args)
                payload = _result_to_payload(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("Tool %s failed: %s", fn_name, e)
            payload = unknown(f"{type(e).__name__}: {str(e)[:300]}")
        status = payload.get("status", "OK")
        self.calls.append(ToolCallRecord(spec.name, spec.server, status, str(payload.get("reason", ""))[:300], spec.source))
        text = json.dumps(payload, default=str)
        if len(text) > _MAX_RESULT_CHARS:
            text = text[:_MAX_RESULT_CHARS] + '... [truncated]"}'
        return text
