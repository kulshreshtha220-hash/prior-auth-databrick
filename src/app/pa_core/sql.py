"""Small helper around the Databricks SQL Statement Execution API.

Used for Delta writes, reference-data lookups and ai_parse_document. Needs a
SQL warehouse id (DATABRICKS_WAREHOUSE_ID). Parameters are always bound, never
string-formatted, to avoid SQL injection.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .config import get_settings
from .llm import workspace_client

logger = logging.getLogger(__name__)


class SqlUnavailable(RuntimeError):
    pass


def _param(name: str, value: Any):
    from databricks.sdk.service.sql import StatementParameterListItem

    if value is None:
        return StatementParameterListItem(name=name, value=None, type="STRING")
    if isinstance(value, bool):
        return StatementParameterListItem(name=name, value=str(value).lower(), type="BOOLEAN")
    if isinstance(value, int):
        return StatementParameterListItem(name=name, value=str(value), type="BIGINT")
    if isinstance(value, float):
        return StatementParameterListItem(name=name, value=repr(value), type="DOUBLE")
    if isinstance(value, (dict, list)):
        value = json.dumps(value, default=str)
    return StatementParameterListItem(name=name, value=str(value), type="STRING")


_SPARK = None


def use_spark(spark) -> None:
    """Register the notebook's SparkSession (agents run in worker threads, where
    the thread-local 'active session' is not visible)."""
    global _SPARK
    _SPARK = spark


def _active_spark():
    """The notebook/job SparkSession, if this code runs on Databricks compute."""
    if _SPARK is not None:
        return _SPARK
    try:
        from pyspark.sql import SparkSession

        return SparkSession.getActiveSession() or getattr(SparkSession, "getDefaultSession", lambda: None)()
    except Exception:  # noqa: BLE001 - not on Databricks compute
        return None


def available() -> bool:
    """True when SQL can run: a SQL warehouse is configured, or we are on Databricks compute."""
    return bool(get_settings().warehouse_id) or _active_spark() is not None


def _execute_spark(spark, statement: str, params: dict[str, Any] | None) -> list[dict]:
    args = {}
    for k, v in (params or {}).items():
        args[k] = json.dumps(v, default=str) if isinstance(v, (dict, list)) else v
    df = spark.sql(statement, args=args or None)
    if not df.columns:
        return []
    return [{c: (None if r[c] is None else str(r[c]) if not isinstance(r[c], (int, float, bool)) else r[c])
             for c in df.columns} for r in df.collect()]


def execute(statement: str, params: dict[str, Any] | None = None, timeout_s: int = 120) -> list[dict]:
    """Run one statement and return rows as dicts (empty list for DML).

    Uses the SQL warehouse (DATABRICKS_WAREHOUSE_ID) when set, e.g. in the app or on
    Model Serving; otherwise the active SparkSession in a notebook or job.
    """
    from databricks.sdk.service.sql import Disposition, Format, StatementState

    s = get_settings()
    if not s.warehouse_id:
        spark = _active_spark()
        if spark is not None:
            return _execute_spark(spark, statement, params)
        raise SqlUnavailable("DATABRICKS_WAREHOUSE_ID is not set")
    w = workspace_client()
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=s.warehouse_id,
        parameters=[_param(k, v) for k, v in (params or {}).items()],
        wait_timeout="30s",
        disposition=Disposition.INLINE,
        format=Format.JSON_ARRAY,
    )
    deadline = time.time() + timeout_s
    while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() > deadline:
            w.statement_execution.cancel_execution(resp.statement_id)
            raise TimeoutError(f"SQL statement timed out after {timeout_s}s")
        time.sleep(1.5)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if not resp.status or resp.status.state != StatementState.SUCCEEDED:
        err = resp.status.error.message if resp.status and resp.status.error else "unknown error"
        raise RuntimeError(f"SQL failed: {err}")
    if not resp.manifest or not resp.result or not resp.result.data_array:
        return []
    cols = [c.name for c in resp.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in resp.result.data_array]


def table(name: str) -> str:
    """Fully qualified, back-quoted table name in the configured schema."""
    s = get_settings()
    return f"`{s.catalog}`.`{s.schema}`.`{name}`"
