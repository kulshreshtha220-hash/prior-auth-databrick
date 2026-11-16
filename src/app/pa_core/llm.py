"""OpenAI-compatible client for Databricks-hosted models.

Two access paths, picked automatically from the model name:
  * Unity Gateway model service  (e.g. ``system.ai.claude-sonnet-4-5``)
      -> ``<host>/ai-gateway/mlflow/v1``
  * Model Serving endpoint        (e.g. ``databricks-claude-sonnet-4-5``)
      -> ``<host>/serving-endpoints``

Auth comes from the Databricks SDK default chain: the app's service principal
in Databricks Apps, automatic passthrough on Model Serving, or a CLI profile /
DATABRICKS_HOST + DATABRICKS_TOKEN locally.
"""
from __future__ import annotations

import functools

from .config import get_settings


@functools.lru_cache(maxsize=1)
def workspace_client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def _bearer_token() -> tuple[str, str]:
    w = workspace_client()
    headers = w.config.authenticate()
    auth = headers.get("Authorization", "")
    token = auth.split(" ", 1)[1] if " " in auth else auth
    return w.config.host.rstrip("/"), token


def api_for(model: str) -> str:
    s = get_settings()
    if s.llm_api in ("gateway", "serving"):
        return s.llm_api
    return "gateway" if model.count(".") >= 2 else "serving"


def openai_client(model: str):
    """Return an OpenAI client pointed at the right Databricks path for `model`.

    A fresh client is built per call so OAuth tokens never go stale.
    """
    from openai import OpenAI

    host, token = _bearer_token()
    base = f"{host}/ai-gateway/mlflow/v1" if api_for(model) == "gateway" else f"{host}/serving-endpoints"
    return OpenAI(api_key=token, base_url=base, timeout=get_settings().agent_timeout_s)
