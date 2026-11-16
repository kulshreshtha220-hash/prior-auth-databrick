"""Shared core for the Prior Authorization Review accelerator on Databricks.

Used by three runtimes:
  * the Databricks App (FastAPI backend + LangGraph orchestrator),
  * the four MLflow ResponsesAgent models on Model Serving,
  * the Lakeflow Jobs (reference refresh, batch evaluation).

Ported from microsoft/Prior-Authorization-Multi-Agent-Solution-Accelerator (MIT).
"""

__version__ = "1.0.0"
