"""Deterministic decision gates and confidence formula ("3 gates, Python rules").

A direct translation of the Microsoft synthesis-decision SKILL.md (LENIENT
mode) into code, so the outcome is reproducible and auditable. The Synthesis
agent then writes the narrative around this fixed outcome.

Outcomes are only APPROVE or PEND, never DENY. Anything uncertain,
including a tool that returned UNKNOWN, ends in PEND for manual review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

APPROVE = "approve"
PEND = "pend_for_review"

NON_BLOCKING_ITEMS = ("insurance id", "insurance plan type", "ncci", "service type")
NON_PENALIZED_ITEMS = ("insurance id", "insurance plan type")
VERIFIED_STATUSES = {"VERIFIED", "ACTIVE", "A"}


@dataclass
class GateOutcome:
    recommendation: str
    decision_gate: str
    confidence: float
    confidence_level: str
    gate_results: dict[str, str]
    gate_reasons: dict[str, list[str]]
    confidence_components: dict[str, float]
    path: str  # "A_policy" | "B_medical_necessity" | "n/a"
    agent_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["synthesis_audit_trail"] = {
            "gates_evaluated": [g for g, r in self.gate_results.items() if r != "NOT_EVALUATED"],
            "gate_results": self.gate_results,
            "gate_reasons": self.gate_reasons,
            "confidence_components": self.confidence_components,
            "medical_necessity_path": self.path,
            "agents_consulted": ["compliance", "clinical", "coverage"],
            "evaluated_by": "pa_core.gates (deterministic)",
        }
        return d


def _status(x) -> str:
    return str(x or "").strip().upper()


def _criteria(coverage: dict) -> list[dict]:
    return [c for c in coverage.get("criteria_assessment") or [] if isinstance(c, dict)]


def _find_criterion(criteria: list[dict], *words: str) -> dict | None:
    for c in criteria:
        name = str(c.get("criterion", "")).lower()
        if all(w in name for w in words):
            return c
    return None


def _is_unknown(text: str) -> bool:
    return "UNKNOWN" in str(text).upper()


def compliance_gaps(compliance: dict, *, blocking_only: bool) -> list[str]:
    gaps = []
    skip = NON_BLOCKING_ITEMS if blocking_only else NON_PENALIZED_ITEMS
    for item in compliance.get("checklist") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("item", ""))
        if any(s in name.lower() for s in skip):
            continue
        if str(item.get("status", "")).lower() in ("incomplete", "missing"):
            gaps.append(f"{name}: {item.get('detail', '')}".strip(": "))
    return gaps


def evaluate(compliance: dict, clinical: dict, coverage: dict, cpt_validation: dict | None) -> GateOutcome:
    results = {"gate_1_provider": "NOT_EVALUATED", "gate_2_codes": "NOT_EVALUATED", "gate_3_necessity": "NOT_EVALUATED"}
    reasons: dict[str, list[str]] = {k: [] for k in results}
    errors = [name for name, r in (("compliance", compliance), ("clinical", clinical), ("coverage", coverage))
              if r.get("error") or r.get("_error")]
    criteria = _criteria(coverage)
    extraction = clinical.get("clinical_extraction") or {}
    ext_conf = float(extraction.get("extraction_confidence") or 0) if isinstance(extraction, dict) else 0.0
    policies = [p for p in coverage.get("coverage_policies") or [] if isinstance(p, dict) and p.get("relevant", True)]
    policy_found = bool(policies)
    path = "A_policy" if policy_found else "B_medical_necessity"
    decision_gate, recommendation = "approved", APPROVE
    path_b_pass = False

    def fail(gate: str, why: str):
        nonlocal decision_gate, recommendation
        results[gate] = "FAIL"
        reasons[gate].append(why)
        decision_gate, recommendation = gate, PEND

    # ---------------- Gate 1: provider
    pv = coverage.get("provider_verification") or {}
    pv_status = _status(pv.get("status")) if isinstance(pv, dict) else ""
    if "coverage" in errors:
        fail("gate_1_provider", "Coverage agent error: provider could not be verified; manual verification required")
    elif pv_status in VERIFIED_STATUSES:
        results["gate_1_provider"] = "PASS"
    elif not pv_status or _is_unknown(pv_status) or _is_unknown(pv.get("detail", "")):
        fail("gate_1_provider", "Provider status UNKNOWN (NPI source unavailable); manual credentialing check required")
    else:
        fail("gate_1_provider", f"Provider NPI status {pv_status}: request credentialing information")

    # ---------------- Gate 2: codes
    if recommendation == APPROVE:
        dx = [d for d in clinical.get("diagnosis_validation") or [] if isinstance(d, dict)]
        if "clinical" in errors or not dx:
            fail("gate_2_codes", "Diagnosis codes could not be validated (clinical agent error or ICD-10 source UNKNOWN)")
        else:
            bad = [d.get("code") for d in dx if not d.get("valid")]
            nonbill = [d.get("code") for d in dx if d.get("valid") and not d.get("billable")]
            if bad:
                fail("gate_2_codes", f"Invalid ICD-10 code(s): {', '.join(map(str, bad))}; request clarification")
            if nonbill:
                fail("gate_2_codes", f"Non-billable ICD-10 code(s): {', '.join(map(str, nonbill))}; request a specific billable code")
        if cpt_validation and not cpt_validation.get("valid", True):
            fail("gate_2_codes", f"Procedure code format invalid: {cpt_validation.get('summary', '')}")
        if results["gate_2_codes"] != "FAIL":
            results["gate_2_codes"] = "PASS"

    # ---------------- Gate 3: medical necessity
    if recommendation == APPROVE:
        gaps = compliance_gaps(compliance, blocking_only=True)
        if "compliance" in errors:
            fail("gate_3_necessity", "Compliance agent error: documentation completeness unknown")
        if gaps:
            fail("gate_3_necessity", "Documentation incomplete: " + "; ".join(gaps))
        not_met = [c.get("criterion") for c in criteria if _status(c.get("status")) == "NOT_MET"]
        insufficient = [c.get("criterion") for c in criteria if _status(c.get("status")) not in ("MET", "NOT_MET")]
        if not_met:
            fail("gate_3_necessity", "Criteria NOT_MET: " + "; ".join(map(str, not_met)))
        if insufficient:
            fail("gate_3_necessity", "Criteria INSUFFICIENT: " + "; ".join(map(str, insufficient)))
        if policy_found:
            if not criteria:
                fail("gate_3_necessity", "Coverage policy found but no criteria were assessed")
        else:
            specialty = _find_criterion(criteria, "specialty")
            severity = extraction.get("severity_indicators") if isinstance(extraction, dict) else None
            if specialty is None:
                fail("gate_3_necessity", "No policy found and provider specialty appropriateness was not assessed")
            if ext_conf < 70:
                fail("gate_3_necessity", f"No policy found and clinical evidence is not strong (extraction confidence {ext_conf:.0f} < 70)")
            if not severity:
                fail("gate_3_necessity", "No policy found and no severity indicators documented")
            path_b_pass = results["gate_3_necessity"] != "FAIL"
        if errors and results["gate_3_necessity"] != "FAIL":
            fail("gate_3_necessity", "Agent error(s): " + ", ".join(errors))
        if results["gate_3_necessity"] != "FAIL":
            results["gate_3_necessity"] = "PASS"
            if not policy_found:
                reasons["gate_3_necessity"].append("Approved under general medical necessity; no specific LCD/NCD applies")

    # ---------------- confidence
    crit_scores = [float(c.get("confidence") or 0) for c in criteria]
    avg_criteria = sum(crit_scores) / len(crit_scores) if crit_scores else 0.0
    compliance_score = max(0.0, 1.0 - 0.1 * len(compliance_gaps(compliance, blocking_only=False)))
    if policy_found:
        align = _find_criterion(criteria, "alignment")
        a = _status(align.get("status")) if align else ("MET" if criteria and not any(
            _status(c.get("status")) != "MET" for c in criteria) else "INSUFFICIENT")
        policy_match = {"MET": 1.0, "NOT_MET": 0.0}.get(a, 0.5)
    else:
        policy_match = 0.75 if path_b_pass else 0.25
    overall = 0.4 * avg_criteria / 100 + 0.3 * ext_conf / 100 + 0.2 * compliance_score + 0.1 * policy_match
    overall -= 0.20 * len(errors)
    overall = round(max(0.0, min(1.0, overall)), 2)
    level = "HIGH" if overall >= 0.80 else "MEDIUM" if overall >= 0.50 else "LOW"

    return GateOutcome(
        recommendation=recommendation,
        decision_gate=decision_gate,
        confidence=overall,
        confidence_level=level,
        gate_results=results,
        gate_reasons=reasons,
        confidence_components={
            "criteria_weight": 0.4, "criteria_score": round(avg_criteria / 100, 4),
            "extraction_weight": 0.3, "extraction_score": round(ext_conf / 100, 4),
            "compliance_weight": 0.2, "compliance_score": round(compliance_score, 4),
            "policy_weight": 0.1, "policy_score": policy_match,
            "agent_error_penalty": round(0.20 * len(errors), 2),
        },
        path=path,
        agent_errors=errors,
    )
