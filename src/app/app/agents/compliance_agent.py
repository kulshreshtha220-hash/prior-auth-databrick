"""Compliance Validation Agent dispatcher (Model Serving endpoint pa-compliance-agent)."""
from app.services.agent_client import invoke_agent


async def run_compliance_review(request_data: dict) -> dict:
    return await invoke_agent("compliance", request_data)
