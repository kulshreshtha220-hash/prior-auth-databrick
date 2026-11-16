"""End-to-end API test in mock mode: SSE review -> stored review -> decision."""
import json

from conftest import SAMPLE
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _stream_review(payload):
    events, result = [], None
    with client.stream("POST", "/api/review/stream", json=payload) as r:
        assert r.status_code == 200
        kind = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1])
                if kind == "result":
                    result = data
                elif kind == "progress":
                    events.append(data)
                elif kind == "error":
                    raise AssertionError(data)
    return events, result


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_full_review_and_decision():
    events, result = _stream_review(SAMPLE)
    pct = [e["progress_pct"] for e in events]
    assert pct == sorted(pct) and pct[-1] == 100
    assert {e["phase"] for e in events} >= {"preflight", "phase_1", "phase_2", "phase_3", "phase_4"}
    assert result["recommendation"] == "approve"
    assert result["confidence_level"] in ("HIGH", "MEDIUM")
    assert result["audit_justification_pdf"]  # base64 PDF
    assert set(result["agent_results"]) == {"compliance", "clinical", "coverage"}
    trail = result["audit_trail"]
    assert trail["data_sources"]

    rid = result["request_id"]
    assert client.get(f"/api/review/{rid}").status_code == 200
    assert any(q["request_id"] == rid for q in client.get("/api/queue").json())

    d = client.post("/api/decision", json={"request_id": rid, "action": "override",
                                           "override_recommendation": "pend_for_review",
                                           "override_rationale": "Need pathology plan", "reviewer_name": "Dr. Test"})
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["final_recommendation"] == "pend_for_review" and body["was_overridden"]
    assert body["letter"]["pdf_base64"]
    assert client.post("/api/decision", json={"request_id": rid, "action": "accept", "reviewer_name": "x"}).status_code == 409


def test_unknown_npi_pends_at_gate_1():
    _, result = _stream_review({**SAMPLE, "provider_npi": "0000000000"})
    assert result["recommendation"] == "pend_for_review"
    assert result["decision_gate"] == "gate_1_provider"


def test_bad_input_rejected():
    r = client.post("/api/review", json={**SAMPLE, "diagnosis_codes": ["XX"]})
    assert r.status_code == 422


def test_same_request_id_is_idempotent():
    import asyncio
    from app.agents.orchestrator import run_multi_agent_review
    first = asyncio.run(run_multi_agent_review(dict(SAMPLE), request_id="fixed-id-1"))
    second = asyncio.run(run_multi_agent_review(dict(SAMPLE), request_id="fixed-id-1"))
    assert first["audit_trail"]["review_started"] == second["audit_trail"]["review_started"]
