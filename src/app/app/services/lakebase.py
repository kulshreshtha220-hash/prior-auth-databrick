"""Lakebase Postgres connections for the app (state store + LangGraph checkpoints).

Databricks Apps injects PGHOST / PGPORT / PGDATABASE / PGUSER when a Lakebase
database resource is attached to the app. The password is a short-lived
OAuth token of the app's service principal, fetched on every new connection,
so it never expires mid-run.
"""
from __future__ import annotations

import functools
import os
import time

_token_cache: dict[str, float | str] = {"token": "", "exp": 0.0}


def _password() -> str:
    if os.environ.get("PGPASSWORD"):
        return os.environ["PGPASSWORD"]
    if time.time() < float(_token_cache["exp"]):
        return str(_token_cache["token"])
    from pa_core.llm import workspace_client

    w = workspace_client()
    tok = w.config.oauth_token().access_token
    _token_cache.update(token=tok, exp=time.time() + 40 * 60)
    return tok


def conninfo() -> str:
    host = os.environ.get("PGHOST")
    if not host:
        raise RuntimeError("Lakebase not attached: PGHOST is not set (add the database resource to the app)")
    return (
        f"host={host} port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'databricks_postgres')} "
        f"user={os.environ.get('PGUSER', '')} sslmode={os.environ.get('PGSSLMODE', 'require')}"
    )


@functools.lru_cache(maxsize=1)
def sync_pool():
    import psycopg
    from psycopg_pool import ConnectionPool

    class TokenConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):  # type: ignore[override]
            kwargs["password"] = _password()
            return super().connect(conninfo, **kwargs)

    return ConnectionPool(conninfo(), connection_class=TokenConnection, min_size=1, max_size=8,
                          max_lifetime=45 * 60, kwargs={"autocommit": True}, open=True)


_async_pool = None


async def async_pool():
    """Async pool for the LangGraph AsyncPostgresSaver checkpointer."""
    global _async_pool
    if _async_pool is None:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        class AsyncTokenConnection(psycopg.AsyncConnection):
            @classmethod
            async def connect(cls, conninfo: str = "", **kwargs):  # type: ignore[override]
                kwargs["password"] = _password()
                return await super().connect(conninfo, **kwargs)

        _async_pool = AsyncConnectionPool(
            conninfo(), connection_class=AsyncTokenConnection, min_size=1, max_size=8, max_lifetime=45 * 60,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=False,
        )
        await _async_pool.open()
    return _async_pool


SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS pa;
CREATE TABLE IF NOT EXISTS pa.cases (
    request_id        TEXT PRIMARY KEY,
    status            TEXT NOT NULL,              -- RUNNING | COMPLETED | FAILED | DECIDED
    progress_pct      INT  DEFAULT 0,
    phase             TEXT,
    patient_name      TEXT,
    provider_npi      TEXT,
    recommendation    TEXT,
    confidence        NUMERIC(4,2),
    confidence_level  TEXT,
    decision_gate     TEXT,
    in_reviewer_queue BOOLEAN DEFAULT FALSE,
    assigned_to       TEXT,
    request_data      JSONB,
    response          JSONB,
    audit_pdf_path    TEXT,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cases_queue ON pa.cases (in_reviewer_queue, created_at DESC);
CREATE TABLE IF NOT EXISTS pa.decisions (
    request_id          TEXT PRIMARY KEY REFERENCES pa.cases(request_id),
    authorization_number TEXT NOT NULL,
    final_recommendation TEXT NOT NULL,
    was_overridden      BOOLEAN NOT NULL,
    override_rationale  TEXT,
    decided_by          TEXT NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL,
    letter              JSONB,
    letter_pdf_path     TEXT
);
CREATE TABLE IF NOT EXISTS pa.audit_events (
    id          BIGSERIAL PRIMARY KEY,
    request_id  TEXT,
    event_type  TEXT NOT NULL,
    actor       TEXT,
    event_data  JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_req ON pa.audit_events (request_id, created_at);
"""


def ensure_schema() -> None:
    with sync_pool().connection() as conn:
        conn.execute(SCHEMA_SQL)
