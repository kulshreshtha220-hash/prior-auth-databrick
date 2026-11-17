"""Lakebase password selection: project endpoint credential vs OAuth token vs PGPASSWORD."""
from types import SimpleNamespace as NS

from app.services import lakebase


def _reset():
    lakebase._token_cache.update(token="", exp=0.0)


def test_project_endpoint_uses_database_credential(monkeypatch):
    _reset()
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setenv("LAKEBASE_ENDPOINT", "projects/pa-lakebase/branches/production/endpoints/primary")
    seen = {}
    fake_w = NS(postgres=NS(generate_database_credential=lambda endpoint: seen.setdefault("ep", endpoint) and NS(token="db-cred")),
                config=NS(oauth_token=lambda: NS(access_token="oauth")))
    monkeypatch.setattr("pa_core.llm.workspace_client", lambda: fake_w)
    assert lakebase._password() == "db-cred"
    assert seen["ep"].startswith("projects/pa-lakebase")


def test_instance_falls_back_to_oauth(monkeypatch):
    _reset()
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.delenv("LAKEBASE_ENDPOINT", raising=False)
    fake_w = NS(config=NS(oauth_token=lambda: NS(access_token="oauth")))
    monkeypatch.setattr("pa_core.llm.workspace_client", lambda: fake_w)
    assert lakebase._password() == "oauth"


def test_pgpassword_wins(monkeypatch):
    _reset()
    monkeypatch.setenv("PGPASSWORD", "local")
    assert lakebase._password() == "local"
