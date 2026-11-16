"""Synthesis Decision Agent dispatcher (Model Serving endpoint pa-synthesis-agent).

The deterministic gate outcome (pa_core.gates) is passed in; the agent writes
the narrative and must keep recommendation / decision_gate / confidence.
"""
from app.services.agent_client import invoke_agent


async def run_synthesis_review(
    request_data: dict,
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    cpt_validation: dict | None = None,
    deterministic_gates: dict | None = None,
) -> dict:
    strip = lambda r: {k: v for k, v in (r or {}).items() if k != "_meta"}  # noqa: E731
    return await invoke_agent("synthesis", {
        "request": request_data,
        "compliance_result": strip(compliance_result),
        "clinical_result": strip(clinical_result),
        "coverage_result": strip(coverage_result),
        "cpt_validation": cpt_validation,
        "deterministic_gates": deterministic_gates,
    })
