"""Deterministic gates must reproduce the Microsoft SKILL.md rubric and worked examples."""
from pa_core import gates


def _compliance(gaps=()):
    items = ["Patient Information", "Provider NPI", "Insurance ID", "Diagnosis Codes", "Procedure Codes",
             "Clinical Notes Presence", "Clinical Notes Quality", "Insurance Plan Type", "NCCI Edit Awareness", "Service Type"]
    return {"checklist": [{"item": i, "status": "missing" if i in gaps else "complete"} for i in items],
            "overall_status": "incomplete" if gaps else "complete"}


def _clinical(ext=92, severity=True, dx_ok=True):
    return {"diagnosis_validation": [{"code": "R91.1", "valid": dx_ok, "billable": True}],
            "clinical_extraction": {"extraction_confidence": ext, "severity_indicators": ["growth"] if severity else []}}


def _coverage(criteria, status="VERIFIED", policies=()):
    return {"provider_verification": {"npi": "1720180003", "status": status},
            "criteria_assessment": [{"criterion": c, "status": s, "confidence": conf} for c, s, conf in criteria],
            "coverage_policies": [{"policy_id": p, "relevant": True} for p in policies]}


CPT_OK = {"valid": True, "summary": "1/1 valid"}


def test_worked_example_strong_evidence_path_b():
    # SKILL.md: scores [95, 85], extraction 92, no gaps, no policy, fallback passes -> 0.91 HIGH, APPROVE
    o = gates.evaluate(_compliance(), _clinical(92), _coverage([("Provider Specialty-Procedure Appropriateness", "MET", 95),
                                                                ("Medical Necessity", "MET", 85)]), CPT_OK)
    assert o.recommendation == gates.APPROVE and o.decision_gate == "approved"
    assert o.confidence == 0.91 and o.confidence_level == "HIGH"


def test_worked_example_weak_evidence_path_b():
    # SKILL.md: scores [95, 25], one INSUFFICIENT -> PEND, 0.74 MEDIUM
    o = gates.evaluate(_compliance(), _clinical(92), _coverage([("Provider Specialty-Procedure Appropriateness", "MET", 95),
                                                                ("Medical Necessity", "INSUFFICIENT", 25)]), CPT_OK)
    assert o.recommendation == gates.PEND and o.decision_gate == "gate_3_necessity"
    assert o.confidence == 0.74 and o.confidence_level == "MEDIUM"


def test_gate1_unknown_provider_pends_not_denies():
    o = gates.evaluate(_compliance(), _clinical(), _coverage([], status="UNKNOWN"), CPT_OK)
    assert o.recommendation == gates.PEND and o.decision_gate == "gate_1_provider"
    assert o.gate_results["gate_2_codes"] == "NOT_EVALUATED"
    assert "UNKNOWN" in o.gate_reasons["gate_1_provider"][0]


def test_gate2_invalid_icd_and_cpt():
    o = gates.evaluate(_compliance(), _clinical(dx_ok=False), _coverage([]), {"valid": False, "summary": "INVALID: 3162"})
    assert o.decision_gate == "gate_2_codes" and len(o.gate_reasons["gate_2_codes"]) == 2


def test_gate3_blocking_documentation_gap_but_insurance_id_is_not_blocking():
    crit = [("Provider Specialty", "MET", 95), ("Medical Necessity", "MET", 90)]
    assert gates.evaluate(_compliance(["Insurance ID"]), _clinical(), _coverage(crit), CPT_OK).recommendation == gates.APPROVE
    o = gates.evaluate(_compliance(["Clinical Notes Quality"]), _clinical(), _coverage(crit), CPT_OK)
    assert o.recommendation == gates.PEND and o.decision_gate == "gate_3_necessity"


def test_path_a_policy_found_requires_all_met():
    crit = [("Diagnosis-Policy Alignment", "MET", 90), ("Criterion 1", "MET", 80)]
    o = gates.evaluate(_compliance(), _clinical(), _coverage(crit, policies=["L35093"]), CPT_OK)
    assert o.recommendation == gates.APPROVE and o.confidence_components["policy_score"] == 1.0
    crit[1] = ("Criterion 1", "NOT_MET", 80)
    assert gates.evaluate(_compliance(), _clinical(), _coverage(crit, policies=["L35093"]), CPT_OK).recommendation == gates.PEND


def test_agent_error_pends_with_penalty():
    clin = _clinical()
    clin["error"] = "timeout"
    o = gates.evaluate(_compliance(), clin, _coverage([("Provider Specialty", "MET", 95)]), CPT_OK)
    assert o.recommendation == gates.PEND
    assert o.confidence_components["agent_error_penalty"] == 0.2


def test_never_deny():
    for status in ("VERIFIED", "INACTIVE", "UNKNOWN"):
        o = gates.evaluate(_compliance(["Provider NPI"]), _clinical(10, False, False),
                           _coverage([("x", "NOT_MET", 0)], status=status), {"valid": False, "summary": ""})
        assert o.recommendation in (gates.APPROVE, gates.PEND)
