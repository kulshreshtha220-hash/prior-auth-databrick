# Prior Authorization Review on Databricks

A Databricks port of Microsoft's
[Prior-Authorization-Multi-Agent-Solution-Accelerator](https://github.com/microsoft/Prior-Authorization-Multi-Agent-Solution-Accelerator)
(MIT). The same four agents (Compliance, Clinical, Coverage, Synthesis), the same SKILL.md rules,
the same five Anthropic healthcare MCP servers and the same UI. Outcomes are only **APPROVE** or **PEND**,
never DENY, and a human reviewer always makes the final call.

**Start here:** [docs/RUNBOOK.md](docs/RUNBOOK.md) (step-by-step setup and deployment).

## How the target diagram maps to this repo

| Diagram box | Implementation | Code |
|---|---|---|
| Databricks Apps, React reviewer UI | Microsoft's Next.js UI as a static export, plus document upload | `frontend/` → built into `src/app/static/` |
| API layer and preflight validation | FastAPI routers, CPT/HCPCS pre-flight | `src/app/app/routers/`, `src/app/app/services/cpt_validation.py` |
| Backend orchestrator (LangGraph, async, checkpointed) | LangGraph graph, Lakebase checkpoints per `request_id` | `src/app/app/agents/orchestrator.py` |
| 3 gates (Python rules) | Deterministic gates + confidence formula from the synthesis SKILL.md | `src/app/pa_core/gates.py` |
| Review orchestration, decision handling | SSE progress, retries, timeouts, audit PDF, letters | `routers/review.py`, `routers/decision.py`, `services/audit_pdf.py`, `services/notification.py` |
| Agent endpoints (MLflow ResponsesAgent on Model Serving) | One agent file, logged 4 times with different config | `src/agents/agent.py`, `src/app/pa_core/agent_runtime.py` |
| Foundation Model APIs via AI Gateway | Unity Gateway model service or serving endpoint, picked from the workspace | `src/app/pa_core/llm.py`, `src/notebooks/00_pick_model.py` |
| MCP client layer | Unity Gateway MCP services, public URLs, or Delta adapters; failures return UNKNOWN | `src/app/pa_core/mcp_tools.py`, `src/app/pa_core/reference.py` |
| UC Volumes | `raw_documents/`, `generated_reports/` | `services/store.py`, `routers/documents.py` |
| Delta tables | `pa_requests`, `documents`, `agent_runs`, `agent_findings`, `gate_results`, `final_decisions`, `audit_events` | `src/sql/ddl_delta.sql` |
| Lakebase Postgres | Live case status, reviewer queue, decisions, audit log, LangGraph checkpoints | `services/lakebase.py`, `services/store.py` |
| Document processing | `ai_parse_document` on uploaded files | `routers/documents.py` |
| Reference data | ICD-10-CM, NCD/LCD, HCPCS, curated CPT, NPI cache | `src/notebooks/05_reference_refresh.py` |
| MLflow 3 tracing, evaluation, inference tables | Traces from app and endpoints; nightly evaluation job | `src/notebooks/06_batch_evaluation.py` |
| Lakeflow Jobs | setup, agents deploy, reference refresh, batch evaluation | `resources/jobs.yml` |
| External healthcare data sources | NPI Registry, ICD-10, CMS Coverage, Clinical Trials, PubMed | `scripts/setup_mcp_services.sh` |

## Repository layout

```
databricks.yml               bundle: variables and targets (dev, prod)
resources/app.yml            the Databricks App and its resources
resources/jobs.yml           4 Lakeflow Jobs
src/app/                     Databricks App source (deployed as-is)
  app.yaml                   app runtime env
  app/                       FastAPI backend (ported from Microsoft backend/app)
  pa_core/                   shared core: config, llm, mcp_tools, agent_runtime, gates, prompts, schemas, skills/
  static/                    built React UI
src/agents/agent.py          MLflow ResponsesAgent (one file for all 4 agents)
src/notebooks/               00 pick model · 01 UC setup · 02 prompts · 03 deploy agent · 04 smoke test
                             05 reference refresh · 06 batch evaluation
src/sql/ddl_delta.sql        Delta tables
frontend/                    React (Next.js) source; rebuild with scripts/build_ui.sh
scripts/                     MCP services, agent identity, UI build, offline bundle schema check
tests/                       33 tests (gates, agent runtime, ResponsesAgent, API flow, Lakebase store on Postgres)
```

## Run locally (no Databricks needed)

```bash
pip install -r src/app/requirements.txt pytest
pytest -q tests                       # 32 tests (+1 needs a Postgres: see tests/test_lakebase_store.py)
cd src/app && PA_AGENT_MODE=mock PA_STATE_STORE=memory PA_USE_PROMPT_REGISTRY=false \
  uvicorn app.main:app --port 8000    # open http://localhost:8000, "Load Sample Case", Submit
```

Run against a real workspace from a laptop, with the agents running inside the app:

```bash
export DATABRICKS_CONFIG_PROFILE=my-ws
cd src/app && PA_AGENT_MODE=inprocess PA_STATE_STORE=memory PA_MCP_MODE=direct \
  PA_LLM_MODEL=system.ai.claude-sonnet-4-5 uvicorn app.main:app --port 8000
```

## Runtime switches (env vars, see `src/app/pa_core/config.py`)

| Variable | Values | Meaning |
|---|---|---|
| `PA_AGENT_MODE` | `endpoint` / `inprocess` / `mock` | Call Model Serving agents, run agents inside the app, or canned results |
| `PA_STATE_STORE` | `lakebase` / `memory` | Lakebase Postgres or in-memory |
| `PA_MCP_MODE` | `service` / `direct` / `off` | Unity Gateway MCP services, public MCP URLs, or no tools |
| `PA_LLM_MODEL` | `system.ai.<model>` / `databricks-<model>` | Model for the agents (per agent: `PA_LLM_MODEL_<AGENT>`) |
| `PA_WRITE_DELTA` | `true` / `false` | Write the analytical record to Delta |
