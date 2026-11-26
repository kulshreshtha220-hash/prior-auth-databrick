"""Central configuration, read from environment variables.

Every runtime (app, serving endpoint, job) reads the same names, so one
setting changes behaviour everywhere. Defaults suit a `dev` deployment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).lower() in ("1", "true", "yes", "on")


AGENT_KEYS = ("compliance", "clinical", "coverage", "synthesis")

# Which MCP servers each agent may call (allow-list, mirrors Microsoft's design).
AGENT_MCP_SERVERS: dict[str, tuple[str, ...]] = {
    "compliance": (),
    "clinical": ("icd10_codes", "pubmed", "clinical_trials"),
    "coverage": ("npi_registry", "cms_coverage"),
    "synthesis": (),
}

# Public endpoints of the Anthropic healthcare MCP servers (used in `direct` mode).
MCP_PUBLIC_URLS: dict[str, str] = {
    "npi_registry": "https://hcls.mcp.claude.com/npi_registry/mcp",
    "icd10_codes": "https://hcls.mcp.claude.com/icd10_codes/mcp",
    "cms_coverage": "https://hcls.mcp.claude.com/cms_coverage/mcp",
    "clinical_trials": "https://hcls.mcp.claude.com/clinical_trials/mcp",
    "pubmed": "https://pubmed.mcp.claude.com/mcp",
}

# Max tool-calling turns per agent (same as Microsoft's max_turns).
AGENT_MAX_TURNS: dict[str, int] = {
    "compliance": 5,
    "clinical": 15,
    "coverage": 15,
    "synthesis": 5,
}


@dataclass
class Settings:
    # Unity Catalog location
    catalog: str = field(default_factory=lambda: _env("PA_CATALOG", "prior_auth"))
    schema: str = field(default_factory=lambda: _env("PA_SCHEMA", "core"))

    # LLM. PA_LLM_MODEL is a UC model service (system.ai.<model>) or a
    # serving endpoint name (databricks-<model>). Per-agent overrides:
    # PA_LLM_MODEL_<AGENT> (e.g. PA_LLM_MODEL_SYNTHESIS).
    llm_model: str = field(default_factory=lambda: _env("PA_LLM_MODEL", "system.ai.claude-sonnet-4-5"))
    # "gateway" -> /ai-gateway/mlflow/v1 (Unity Gateway), "serving" -> /serving-endpoints
    llm_api: str = field(default_factory=lambda: _env("PA_LLM_API", "auto"))
    llm_temperature: float = field(default_factory=lambda: float(_env("PA_LLM_TEMPERATURE", "0")))
    llm_max_tokens: int = field(default_factory=lambda: int(_env("PA_LLM_MAX_TOKENS", "8000")))

    # MCP. "service": Unity Gateway MCP services (recommended);
    # "direct": public URLs (local dev, or if MCP services are unavailable);
    # "off": no tools (every tool answers UNKNOWN).
    mcp_mode: str = field(default_factory=lambda: _env("PA_MCP_MODE", "service"))
    # Catalog.schema that holds the MCP services (default: the same schema as the tables)
    mcp_service_schema: str = field(default_factory=lambda: _env("PA_MCP_SERVICE_SCHEMA", ""))
    mcp_timeout_s: float = field(default_factory=lambda: float(_env("PA_MCP_TIMEOUT_S", "60")))
    # Per-source override: where each data source comes from.
    #   "uc"  = Unity Catalog reference tables (no MCP call)
    #   "mcp" = live MCP server (mode from PA_MCP_MODE), with UC fallback
    #   "off" = disabled (checks that need it report UNKNOWN)
    # e.g. PA_DATA_SOURCES="icd10_codes:uc,npi_registry:uc,cms_coverage:uc,pubmed:mcp,clinical_trials:mcp"
    # Sources not listed use "mcp".
    data_sources: str = field(default_factory=lambda: _env("PA_DATA_SOURCES", ""))
    # Fall back to Delta reference tables when a live tool is unavailable.
    reference_fallback: bool = field(default_factory=lambda: _env_bool("PA_REFERENCE_FALLBACK", True))

    # SQL warehouse (Delta writes, ai_parse_document, reference lookups)
    warehouse_id: str = field(default_factory=lambda: _env("DATABRICKS_WAREHOUSE_ID"))

    # Prompt Registry: load SKILL.md prompts from UC (alias) or local files.
    prompt_alias: str = field(default_factory=lambda: _env("PA_PROMPT_ALIAS", "prod"))
    use_prompt_registry: bool = field(default_factory=lambda: _env_bool("PA_USE_PROMPT_REGISTRY", True))

    # Agent dispatch from the app: "endpoint" (Model Serving), "inprocess", "mock"
    agent_mode: str = field(default_factory=lambda: _env("PA_AGENT_MODE", "endpoint"))
    agent_endpoint_prefix: str = field(default_factory=lambda: _env("PA_AGENT_ENDPOINT_PREFIX", "pa"))
    agent_timeout_s: float = field(default_factory=lambda: float(_env("PA_AGENT_TIMEOUT_S", "300")))

    # Persistence: "lakebase" (Postgres), "memory" (local dev)
    state_store: str = field(default_factory=lambda: _env("PA_STATE_STORE", "lakebase"))
    write_delta: bool = field(default_factory=lambda: _env_bool("PA_WRITE_DELTA", True))

    # MLflow experiment for traces from the app
    mlflow_experiment: str = field(default_factory=lambda: _env("PA_MLFLOW_EXPERIMENT", ""))

    # Who may see every user's cases (the clinical reviewers): comma-separated emails, or "*" for all.
    # Everyone else sees only the cases they submitted.
    reviewers: str = field(default_factory=lambda: _env("PA_REVIEWERS", ""))
    # Let the person who submitted a case also record its final decision (demo). Set false in production
    # so only reviewers decide.
    allow_self_decision: bool = field(default_factory=lambda: _env_bool("PA_ALLOW_SELF_DECISION", True))

    def is_reviewer(self, email: str | None) -> bool:
        names = {e.strip().lower() for e in self.reviewers.split(",") if e.strip()}
        return "*" in names or bool(email and email.strip().lower() in names)

    @property
    def fq_schema(self) -> str:
        return f"{self.catalog}.{self.schema}"

    @property
    def raw_documents_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/raw_documents"

    @property
    def generated_reports_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/generated_reports"

    @property
    def mcp_schema(self) -> str:
        return self.mcp_service_schema or self.fq_schema

    def source_mode(self, server: str) -> str:
        for part in self.data_sources.split(","):
            if ":" in part:
                name, mode = (x.strip().lower() for x in part.split(":", 1))
                if name == server and mode in ("uc", "mcp", "off"):
                    return mode
        return "off" if self.mcp_mode == "off" else "mcp"

    def model_for(self, agent_key: str) -> str:
        return _env(f"PA_LLM_MODEL_{agent_key.upper()}") or self.llm_model

    def endpoint_for(self, agent_key: str) -> str:
        return _env(f"PA_AGENT_ENDPOINT_{agent_key.upper()}") or f"{self.agent_endpoint_prefix}-{agent_key}-agent"

    def prompt_name(self, agent_key: str) -> str:
        return f"{self.fq_schema}.{agent_key}_skill"


def get_settings() -> Settings:
    return Settings()
