"""UC data-source mode: per-source routing, NPI check digit, reference tools with a fake SQL layer."""
import json

import pa_core.reference as ref
from pa_core.config import get_settings
from pa_core.mcp_tools import Toolbox


def test_source_mode_parsing(monkeypatch):
    monkeypatch.setenv("PA_DATA_SOURCES", "icd10_codes:uc, npi_registry:UC,pubmed:off")
    monkeypatch.setenv("PA_MCP_MODE", "direct")
    s = get_settings()
    assert s.source_mode("icd10_codes") == "uc" and s.source_mode("npi_registry") == "uc"
    assert s.source_mode("pubmed") == "off" and s.source_mode("cms_coverage") == "mcp"


def test_toolbox_uses_uc_tools_without_calling_mcp(monkeypatch):
    monkeypatch.setenv("PA_DATA_SOURCES", "npi_registry:uc,cms_coverage:uc")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh1")
    box = Toolbox.for_agent("coverage")
    assert {t.name for t in box.tools} == {"ref_npi_lookup", "ref_coverage_search", "ref_coverage_document"}
    assert not box.unavailable and not box._servers  # no MCP connection attempted
    note = box.availability_note()
    assert "npi_lookup -> ref_npi_lookup" in note and "UNAVAILABLE" not in note.upper().replace("AVAILABILITY", "")


def test_uc_mode_without_warehouse_is_unknown(monkeypatch):
    monkeypatch.setenv("PA_DATA_SOURCES", "icd10_codes:uc,pubmed:off,clinical_trials:off")
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    box = Toolbox.for_agent("clinical")
    assert "warehouse" in box.unavailable["icd10_codes"].lower()
    assert set(box.unavailable) == {"icd10_codes", "pubmed", "clinical_trials"}


def test_npi_check_digit():
    assert ref.npi_check_digit_ok("1720180003")      # real pulmonologist from the sample case
    assert not ref.npi_check_digit_ok("1234567890")  # fails the check digit
    assert not ref.npi_check_digit_ok("12345")


def test_icd10_lookup_marks_invalid_and_non_billable(monkeypatch):
    def fake_exec(stmt, params=None, timeout_s=120):
        if "LIKE concat" in stmt:
            return [{"code": "M17.11", "description": "Unilateral primary osteoarthritis, right knee"}]
        return [{"code": "R91.1", "description": "Solitary pulmonary nodule", "billable": "true", "code_set_version": "FY2026"},
                {"code": "M17.1", "description": "Unilateral primary osteoarthritis of knee", "billable": "false", "code_set_version": "FY2026"}]
    monkeypatch.setattr(ref.sql, "execute", fake_exec)
    out = ref.call("ref_icd10_lookup", {"codes": ["R91.1", "M17.1", "R99.99"]})["results"]
    by = {r["code"].replace(".", ""): r for r in out}
    assert by["R911"]["billable"] is True
    assert by["M171"]["billable"] is False and by["M171"]["billable_children"][0]["code"] == "M17.11"
    assert by["R9999"]["valid"] is False


def test_npi_lookup_invalid_never_calls_api(monkeypatch):
    monkeypatch.setattr(ref, "_nppes_fetch", lambda npi: (_ for _ in ()).throw(AssertionError("no API call")))
    assert ref.call("ref_npi_lookup", {"npi": "1234567890"})["status"] == "invalid"


def test_npi_lookup_cache_miss_fetches_and_caches(monkeypatch):
    calls = []
    def fake_exec(stmt, params=None, timeout_s=120):
        calls.append(stmt.split()[0])
        return []
    monkeypatch.setattr(ref.sql, "execute", fake_exec)
    monkeypatch.setattr(ref, "_nppes_fetch", lambda npi: {"npi": npi, "name": "CHARLES ABATE, MD", "taxonomy": "207RP1001X",
                                                           "taxonomy_desc": "Pulmonary Disease", "state": "FL", "status": "active"})
    out = ref.call("ref_npi_lookup", {"npi": "1720180003"})
    assert out["status"] == "active" and out["taxonomy_desc"] == "Pulmonary Disease"
    assert calls == ["SELECT", "MERGE"]


def test_reference_tool_result_flows_through_toolbox(monkeypatch):
    monkeypatch.setenv("PA_DATA_SOURCES", "cms_coverage:uc")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh1")
    monkeypatch.setattr(ref.sql, "execute", lambda *a, **k: [])
    box = Toolbox.for_agent("coverage")
    fn = next(t.fn_name for t in box.tools if t.name == "ref_coverage_search")
    payload = json.loads(box.call(fn, '{"keywords": "bronchoscopy lung biopsy"}'))
    assert payload["status"] == "OK" and payload["data"]["results"] == []
    assert box.calls[-1].source == "reference"


def test_spark_backend_used_when_no_warehouse(monkeypatch):
    import pa_core.sql as sqlmod
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)

    class FakeDF:
        columns = ["code", "billable"]
        def collect(self):
            return [{"code": "R91.1", "billable": True}]

    seen = {}
    class FakeSpark:
        def sql(self, stmt, args=None):
            seen.update(stmt=stmt, args=args)
            return FakeDF()

    sqlmod.use_spark(FakeSpark())
    try:
        assert sqlmod.available()
        rows = sqlmod.execute("SELECT ... WHERE x IN (SELECT explode(from_json(:codes, 'array<string>')))", {"codes": ["R911"]})
        assert rows == [{"code": "R91.1", "billable": True}] and seen["args"] == {"codes": '["R911"]'}
    finally:
        sqlmod.use_spark(None)
