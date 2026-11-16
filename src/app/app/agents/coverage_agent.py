"""Coverage Assessment Agent dispatcher (Model Serving endpoint pa-coverage-agent)."""
from app.services.agent_client import invoke_agent


async def run_coverage_review(request_data: dict, clinical_findings: dict) -> dict:
    return await invoke_agent("coverage", {"request": request_data, "clinical_findings": clinical_findings})
