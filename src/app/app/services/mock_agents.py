"""Canned agent results for PA_AGENT_MODE=mock (UI demos, CI, smoke tests).

Shaped like the Microsoft sample case (CT-guided lung biopsy). No LLM calls.
Special NPI 0000000000 simulates an unavailable NPI source (UNKNOWN).
"""
from __future__ import annotations


def _req(payload: dict) -> dict:
    return payload.get("request", payload)


def mock_result(agent_key: str, payload: dict) -> dict:
    req = _req(payload)
    if agent_key == "compliance":
        items = ["Patient Information", "Provider NPI", "Insurance ID", "Diagnosis Codes", "Procedure Codes",
                 "Clinical Notes Presence", "Clinical Notes Quality", "Insurance Plan Type",
                 "NCCI Edit Awareness", "Service Type"]
        notes_ok = len(str(req.get("clinical_notes", ""))) > 80
        checklist = [{"item": i, "status": "complete", "detail": "Present"} for i in items]
        if not notes_ok:
            checklist[6] = {"item": "Clinical Notes Quality", "status": "incomplete", "detail": "Notes too brief"}
        return {
            "agent_name": "Compliance Agent",
            "checklist": checklist,
            "overall_status": "complete" if notes_ok else "incomplete",
            "missing_items": [] if notes_ok else ["Clinical Notes Quality"],
            "additional_info_requests": [],
            "error": None,
        }
    if agent_key == "clinical":
        return {
            "agent_name": "Clinical Reviewer Agent",
            "diagnosis_validation": [
                {"code": c, "valid": True, "description": f"Mock description for {c}", "billable": True}
                for c in req.get("diagnosis_codes", [])
            ],
            "procedure_validation": [
                {"code": c, "valid": True, "description": "Mock procedure", "source": "orchestrator_preflight"}
                for c in req.get("procedure_codes", [])
            ],
            "clinical_extraction": {
                "chief_complaint": "Persistent pulmonary nodule with cough",
                "history_of_present_illness": "Enlarging nodule on serial CT",
                "prior_treatments": ["Antibiotic course without resolution"],
                "severity_indicators": ["Nodule growth 8mm to 14mm", "PET avid"],
                "functional_limitations": [],
                "diagnostic_findings": ["CT chest: 14mm RUL nodule"],
                "duration_and_progression": "3 months, enlarging",
                "medical_history_and_comorbidities": "30 pack-year smoking history",
                "extraction_confidence": 88,
            },
            "literature_support": [{"title": "Mock guideline reference", "pmid": "00000000", "relevance": "Biopsy of growing nodules"}],
            "clinical_trials": [],
            "clinical_summary": "Growing PET-avid nodule; tissue diagnosis indicated.",
            "tool_results": [{"tool_name": "icd10_codes:validate_code", "status": "pass", "detail": "mock"}],
            "error": None,
        }
    if agent_key == "coverage":
        npi = str(req.get("provider_npi", ""))
        unknown = npi == "0000000000"
        return {
            "agent_name": "Coverage Agent",
            "provider_verification": {
                "npi": npi, "name": "" if unknown else "Mock Pulmonology Provider",
                "specialty": "" if unknown else "Pulmonary Disease",
                "status": "UNKNOWN" if unknown else "VERIFIED",
                "detail": "UNKNOWN - NPI source unavailable" if unknown else "Active in NPPES (mock)",
            },
            "coverage_policies": [],
            "criteria_assessment": [
                {"criterion": "Provider Specialty-Procedure Appropriateness", "status": "MET", "confidence": 95,
                 "evidence": ["Pulmonologist performing bronchoscopic biopsy"], "notes": "", "source": "npi_registry", "met": True},
                {"criterion": "Medical Necessity (general)", "status": "MET", "confidence": 85,
                 "evidence": ["Enlarging nodule"], "notes": "", "source": "clinical", "met": True},
            ],
            "coverage_criteria_met": ["Provider specialty", "Medical necessity"],
            "coverage_criteria_not_met": [],
            "policy_references": [],
            "coverage_limitations": ["No specific NCD/LCD found (mock)"],
            "documentation_gaps": [],
            "tool_results": [{"tool_name": "npi_registry:npi_lookup", "status": "warning" if unknown else "pass",
                              "detail": "UNKNOWN - mock outage" if unknown else "mock"}],
            "error": None,
        }
    # synthesis: echo the deterministic outcome and add narrative
    g = payload.get("deterministic_gates") or {}
    import json

    return {
        "recommendation": g.get("recommendation", "pend_for_review"),
        "confidence": g.get("confidence", 0.5),
        "confidence_level": g.get("confidence_level", "MEDIUM"),
        "summary": "Mock synthesis based on deterministic gate results.",
        "clinical_rationale": "; ".join(sum((v for v in (g.get("gate_reasons") or {}).values()), [])) or "All gates passed.",
        "decision_gate": g.get("decision_gate", "gate_3_necessity"),
        "coverage_criteria_met": [], "coverage_criteria_not_met": [], "missing_documentation": [],
        "policy_references": [], "criteria_summary": "",
        "synthesis_audit_trail": json.dumps(g.get("synthesis_audit_trail", {})),
        "disclaimer": "AI-assisted draft (mock). Human clinical review required before final determination.",
    }
