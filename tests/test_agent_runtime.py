"""Agent runtime: tool loop, UNKNOWN on tool failure, JSON extraction, schema validation."""
import json
from types import SimpleNamespace as NS

import pa_core.agent_runtime as rt
from pa_core.mcp_tools import Toolbox, ToolSpec


class _FakeServer:
    def call_tool(self, name, args):
        raise ConnectionError("MCP server down")


def _fake_box(agent_key):
    box = Toolbox(agent_key)
    box.tools.append(ToolSpec("npi_registry", "npi_lookup", "lookup", {"type": "object", "properties": {}}, "mcp"))
    box._servers["npi_registry"] = _FakeServer()
    box.unavailable["cms_coverage"] = "ConnectError: timeout"
    return box


class _FakeCompletions:
    def __init__(self):
        self.calls = 0
        self.seen_system = ""

    def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            self.seen_system = kw["messages"][0]["content"]
            tc = NS(id="c1", function=NS(name="npi_registry__npi_lookup", arguments='{"npi":"1720180003"}'))
            msg = NS(tool_calls=[tc], content=None, model_dump=lambda **k: {"role": "assistant", "content": None,
                     "tool_calls": [{"id": "c1", "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}]})
            return NS(choices=[NS(message=msg)])
        tool_msg = kw["messages"][-1]
        assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["status"] == "UNKNOWN"
        final = {"provider_verification": {"npi": "1720180003", "status": "UNKNOWN", "detail": "UNKNOWN - source down"},
                 "criteria_assessment": [], "tool_results": []}
        return NS(choices=[NS(message=NS(tool_calls=None, content="```json\n" + json.dumps(final) + "\n```"))])


def test_tool_failure_becomes_unknown(monkeypatch):
    fake = _FakeCompletions()
    monkeypatch.setattr(rt, "openai_client", lambda model: NS(chat=NS(completions=fake)))
    monkeypatch.setattr(rt.Toolbox, "for_agent", classmethod(lambda cls, k: _fake_box(k)))
    out = rt.run_agent("coverage", {"request": {"provider_npi": "1720180003"}})
    assert out["provider_verification"]["status"] == "UNKNOWN"
    assert out.get("error") is None
    details = " ".join(t["detail"] for t in out["tool_results"])
    assert "UNKNOWN" in details and "cms_coverage" in " ".join(t["tool_name"] for t in out["tool_results"])
    assert "TOOL AVAILABILITY NOTICE" in fake.seen_system
    assert out["_meta"]["tool_calls"][0]["status"] == "UNKNOWN"


def test_llm_failure_returns_error_not_exception(monkeypatch):
    def boom(model):
        raise RuntimeError("no model access")
    monkeypatch.setattr(rt, "openai_client", boom)
    monkeypatch.setattr(rt.Toolbox, "for_agent", classmethod(lambda cls, k: Toolbox(k)))
    out = rt.run_agent("compliance", {"patient_name": "x"})
    assert out["error"] and "no model access" in out["error"]


def test_skill_prompts_load_for_all_agents():
    from pa_core.prompts import system_prompt
    for k in ("compliance", "clinical", "coverage", "synthesis"):
        text, src = system_prompt(k)
        assert "bundled SKILL.md" in src and len(text) > 1000
    assert "DATABRICKS DEPLOYMENT OVERRIDE" in system_prompt("synthesis")[0]


def test_model_written_error_becomes_warning(monkeypatch):
    final = {"checklist": [], "overall_status": "complete", "error": "PubMed search partially failed"}
    comp = NS(create=lambda **kw: NS(choices=[NS(message=NS(tool_calls=None, content=json.dumps(final)))]))
    monkeypatch.setattr(rt, "openai_client", lambda model: NS(chat=NS(completions=comp)))
    monkeypatch.setattr(rt.Toolbox, "for_agent", classmethod(lambda cls, k: Toolbox(k)))
    out = rt.run_agent("compliance", {"patient_name": "x"})
    assert out["error"] is None
