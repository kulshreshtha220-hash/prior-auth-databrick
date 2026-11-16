"""Lakebase store + LangGraph Postgres checkpointer against a real Postgres.

Skipped unless PA_TEST_PGHOST is set, e.g.:
  PA_TEST_PGHOST=localhost PA_TEST_PGUSER=patest PA_TEST_PGPASSWORD=patest pytest tests/test_lakebase_store.py
"""
import asyncio
import importlib
import os

import pytest
from conftest import SAMPLE

pytestmark = pytest.mark.skipif(not os.environ.get("PA_TEST_PGHOST"), reason="no test Postgres")


@pytest.fixture(scope="module")
def lakebase_env():
    os.environ.update(PGHOST=os.environ["PA_TEST_PGHOST"], PGUSER=os.environ["PA_TEST_PGUSER"],
                      PGPASSWORD=os.environ["PA_TEST_PGPASSWORD"], PGDATABASE="databricks_postgres",
                      PGSSLMODE="disable", PA_STATE_STORE="lakebase")
    import app.agents.orchestrator as orch
    from app.services import lakebase
    lakebase.ensure_schema()
    with lakebase.sync_pool().connection() as c:
        c.execute("TRUNCATE pa.decisions, pa.audit_events, pa.cases")
    orch._graph = None  # rebuild with the Postgres checkpointer
    yield orch
    os.environ["PA_STATE_STORE"] = "memory"
    orch._graph = None


def test_review_and_decision_persist(lakebase_env):
    orch = lakebase_env
    from app.services import store
    rid = "lb-test-1"
    store.start_case(rid, dict(SAMPLE), "tester@x.com")
    result = asyncio.run(orch.run_multi_agent_review(dict(SAMPLE), request_id=rid))
    from app.routers.review import _build_review_response
    resp = _build_review_response(rid, result).model_dump()
    store.store_review(rid, dict(SAMPLE), resp)

    got = store.get_review(rid)
    assert got and got["response"]["recommendation"] == "approve" and got["decision"] is None
    assert store.case_status(rid)["status"] == "COMPLETED"
    assert any(q["request_id"] == rid for q in store.reviewer_queue())

    store.store_decision(rid, {"request_id": rid, "authorization_number": "PA-1", "final_recommendation": "approve",
                               "decided_by": "Dr. X", "decided_at": "2026-11-16T10:00:00+00:00", "was_overridden": False,
                               "override_rationale": None, "letter": {"letter_type": "approval"}})
    got = store.get_review(rid)
    assert got["decision"]["authorization_number"] == "PA-1"
    assert store.case_status(rid)["status"] == "DECIDED"
    assert not any(q["request_id"] == rid for q in store.reviewer_queue())

    from app.services.lakebase import sync_pool
    with sync_pool().connection() as c:
        events = [r[0] for r in c.execute("SELECT event_type FROM pa.audit_events WHERE request_id=%s ORDER BY id", (rid,))]
        cps = c.execute("SELECT count(*) FROM checkpoints WHERE thread_id=%s", (rid,)).fetchone()[0]
    assert events == ["review_started", "review_completed", "decision_recorded"]
    assert cps > 0  # LangGraph checkpoints written to Postgres

    again = asyncio.run(orch.run_multi_agent_review(dict(SAMPLE), request_id=rid))
    assert again["audit_trail"]["review_started"] == result["audit_trail"]["review_started"]
