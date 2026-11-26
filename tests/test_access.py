"""Per-user case visibility: users see their own cases, reviewers see everyone's."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("PA_AGENT_MODE", "mock")
    monkeypatch.setenv("PA_STATE_STORE", "memory")
    monkeypatch.setenv("PA_WRITE_DELTA", "false")
    monkeypatch.setenv("PA_REVIEWERS", "reviewer@x.com")
    from app.main import app

    return TestClient(app)


SAMPLE = json.load(open("tests/eval_cases.json"))[0]["request"]


def _submit(client, email):
    kind = None
    with client.stream("POST", "/api/review/stream", json=SAMPLE, headers={"x-forwarded-email": email}) as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and kind == "result":
                return json.loads(line.split(":", 1)[1])["request_id"]
    raise AssertionError("no result")


def test_users_see_only_their_cases(client):
    a = _submit(client, "doc.a@x.com")
    b = _submit(client, "doc.b@x.com")
    ha, hb, hr = ({"x-forwarded-email": e} for e in ("doc.a@x.com", "doc.b@x.com", "reviewer@x.com"))

    mine_a = {c["request_id"] for c in client.get("/api/my-cases", headers=ha).json()}
    assert a in mine_a and b not in mine_a
    q_a = {c["request_id"] for c in client.get("/api/queue", headers=ha).json()}
    assert b not in q_a
    q_r = {c["request_id"] for c in client.get("/api/queue", headers=hr).json()}
    assert {a, b} <= q_r

    assert client.get(f"/api/review/{b}", headers=ha).status_code == 403
    assert client.get(f"/api/review/{b}", headers=hb).status_code == 200
    assert client.get(f"/api/review/{b}", headers=hr).status_code == 200
    assert client.get("/api/me", headers=hr).json()["is_reviewer"] is True
    assert client.get("/api/me", headers=ha).json()["is_reviewer"] is False

    d = {"request_id": b, "action": "accept", "reviewer_name": "x"}
    assert client.post("/api/decision", json=d, headers=ha).status_code == 403
    assert client.post("/api/decision", json=d, headers=hr).status_code == 200
