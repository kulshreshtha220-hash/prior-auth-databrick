"""FastAPI entry point for the Databricks App.

Serves the API under /api and the static React UI (built Next.js export in
./static) from the same origin, so the browser needs no CORS or API URL.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import agents, decision, documents, review
from pa_core.config import get_settings

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("app").setLevel(getattr(logging, _log_level, logging.INFO))
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(_app):
    _startup()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Prior Authorization Review API",
    description="Multi-agent prior authorization review on Databricks (Model Serving agents, LangGraph, Lakebase, Unity Catalog)",
    version="1.0.0",
)

if "localhost" in settings.FRONTEND_ORIGIN or "127.0.0.1" in settings.FRONTEND_ORIGIN:
    app.add_middleware(CORSMiddleware, allow_origins=[settings.FRONTEND_ORIGIN, "http://localhost:3000"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(review.router, prefix="/api")
app.include_router(decision.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(documents.router, prefix="/api")


def _startup() -> None:
    s = get_settings()
    logger.info("Starting: agent_mode=%s state_store=%s mcp_mode=%s model=%s", s.agent_mode, s.state_store,
                s.mcp_mode, s.llm_model)
    if s.mlflow_experiment:
        try:
            import mlflow

            mlflow.set_tracking_uri("databricks")
            exp = s.mlflow_experiment
            # app resource "MLflow experiment" injects the experiment id; a path also works
            if exp.isdigit():
                mlflow.set_experiment(experiment_id=exp)
            else:
                mlflow.set_experiment(exp)
            mlflow.openai.autolog()  # one span per LLM call (prompt, tokens, latency)
            logger.info("MLflow tracing on: experiment %s", exp)
        except Exception as e:  # noqa: BLE001
            logger.warning("MLflow tracing disabled: %s", e)
    if s.state_store == "lakebase":
        try:
            from app.services.lakebase import ensure_schema

            ensure_schema()
        except Exception as e:  # noqa: BLE001
            logger.error("Lakebase schema check failed: %s", e)


@app.get("/health")
async def health():
    s = get_settings()
    return {"status": "ok", "agent_mode": s.agent_mode, "state_store": s.state_store, "mcp_mode": s.mcp_mode}


@app.get("/api/config")
async def ui_config():
    s = get_settings()
    return {"catalog": s.catalog, "schema": s.schema, "agent_mode": s.agent_mode, "model": s.llm_model}


_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/_next", StaticFiles(directory=_static / "_next"), name="next-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = (_static / path).resolve()
        if path and f.is_file() and _static in f.parents:
            return FileResponse(f)
        html = _static / f"{path}.html"
        if path and html.is_file():
            return FileResponse(html)
        return FileResponse(_static / "index.html")
