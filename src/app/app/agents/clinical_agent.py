"""Clinical Reviewer Agent dispatcher (Model Serving endpoint pa-clinical-agent)."""
from app.services.agent_client import invoke_agent


async def run_clinical_review(request_data: dict) -> dict:
    return await invoke_agent("clinical", request_data)
