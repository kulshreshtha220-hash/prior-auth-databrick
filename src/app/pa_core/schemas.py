"""Structured output schemas for the four agents.

Copied from the Microsoft accelerator (agents/*/schemas.py, MIT) and merged.
Every agent's final answer is validated against one of these models.
"""
import json
import re
import typing
from typing import Literal

from pydantic import BaseModel as _PydanticBase
from pydantic import model_validator


def _to_text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for key in ("value", "text", "summary", "description"):
            if isinstance(v.get(key), str):
                return v[key]
        return "; ".join(f"{k}: {_to_text(x)}" for k, x in v.items() if x not in (None, "", []))
    if isinstance(v, (list, tuple)):
        return "; ".join(_to_text(x) for x in v if x not in (None, "", []))
    return str(v)


def _to_number(v, confidence: bool):
    if isinstance(v, bool):
        return v
    if isinstance(v, dict):
        v = v.get("value", v.get("score", v.get("confidence")))
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if not m:
            return v
        pct = "%" in v
        v = float(m.group())
        if pct:
            return int(round(v))
    if isinstance(v, float):
        if confidence and 0 < v <= 1:  # 0.92 means 92%
            v *= 100
        return int(round(v))
    return v


class BaseModel(_PydanticBase):
    """Tolerant base for LLM output.

    The LLM sometimes writes a valid answer in a slightly different JSON shape: null for an
    optional field, a list where text is expected, 92.5 or "92%" or 0.92 for a 0-100 score.
    Pydantic would reject the whole object and the agent's finding would be lost (live bugs
    2026-11-26: diagnosis_validation and clinical_extraction dropped). Here each field is
    coerced to its declared type first; values that still do not fit are left to Pydantic.
    """

    @classmethod
    def _prepare(cls, data: dict) -> dict:
        return data

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data):
        if not isinstance(data, dict):
            return data
        data = cls._prepare({k: v for k, v in data.items() if v is not None})
        out = {}
        for k, v in data.items():
            f = cls.model_fields.get(k)
            if f is None:
                out[k] = v
                continue
            ann = f.annotation
            origin, args = typing.get_origin(ann), typing.get_args(ann)
            if ann is str and not isinstance(v, str):
                v = _to_text(v)
            elif ann is int:
                v = _to_number(v, confidence="confidence" in k)
            elif ann is float and isinstance(v, str):
                n = _to_number(v, confidence=False)
                v = float(n) if isinstance(n, (int, float)) else v
            elif ann is bool and isinstance(v, str):
                v = v.strip().lower() in ("true", "yes", "y", "1", "met", "valid")
            elif origin is list and args and args[0] is str:
                if isinstance(v, str):
                    v = [v] if v.strip() else []
                elif isinstance(v, dict):
                    v = [f"{a}: {_to_text(b)}" for a, b in v.items()]
                elif isinstance(v, list):
                    v = [_to_text(x) for x in v if x not in (None, "")]
            out[k] = v
        return out


class AgentCheck(BaseModel):
    """A single rule/check that an agent performed."""

    rule: str = ""
    result: str = "info"  # "pass", "fail", "warning", "info"
    detail: str = ""


class ChecklistItem(BaseModel):
    item: str = ""
    status: str = "incomplete"  # "complete", "incomplete", "missing"
    detail: str = ""


class ComplianceResult(BaseModel):
    agent_name: str = "Compliance Agent"
    checks_performed: list[AgentCheck] = []
    checklist: list[ChecklistItem] = []
    overall_status: str = "incomplete"
    missing_items: list[str] = []
    additional_info_requests: list[str] = []
    error: str | None = None


class ToolResult(BaseModel):
    tool_name: str = ""
    status: str = "warning"  # "pass", "fail", "warning"
    detail: str = ""


class DiagnosisValidation(BaseModel):
    code: str = ""
    valid: bool = False
    description: str = ""
    billable: bool = False
    hierarchy_note: str = ""  # only when non-billable code has specific children


class ClinicalExtraction(BaseModel):
    @classmethod
    def _prepare(cls, data: dict) -> dict:
        """Accept per-field objects ({"value": ..., "confidence": 95}) and, if the overall
        extraction_confidence is missing, use the average of the field scores (SKILL.md Step 4)."""
        field_scores = []
        out = {}
        for k, v in data.items():
            if isinstance(v, dict) and k != "extraction_confidence" and ("value" in v or "confidence" in v):
                if v.get("confidence") is not None:
                    n = _to_number(v["confidence"], confidence=True)
                    if isinstance(n, int):
                        field_scores.append(n)
                v = v.get("value", "")
            out[k] = v
        scores = out.get("field_confidence") or out.get("field_scores") or out.get("confidence_by_field")
        if isinstance(scores, dict):
            for x in scores.values():
                n = _to_number(x, confidence=True)
                if isinstance(n, int):
                    field_scores.append(n)
        if out.get("extraction_confidence") in (None, "") and field_scores:
            out["extraction_confidence"] = round(sum(field_scores) / len(field_scores))
        return out

    chief_complaint: str = ""
    history_of_present_illness: str = ""
    prior_treatments: list[str] = []
    severity_indicators: list[str] = []
    functional_limitations: list[str] = []
    diagnostic_findings: list[str] = []
    duration_and_progression: str = ""
    medical_history_and_comorbidities: str = ""
    extraction_confidence: int = 0  # 0-100 overall extraction confidence


class ProcedureValidation(BaseModel):
    code: str = ""
    valid: bool = False
    description: str = ""
    source: str = ""  # "orchestrator_preflight" or "unverified"


class LiteratureReference(BaseModel):
    title: str = ""
    pmid: str = ""
    relevance: str = ""


class ClinicalTrialReference(BaseModel):
    nct_id: str = ""
    title: str = ""
    status: str = ""
    relevance: str = ""


class ClinicalResult(BaseModel):
    agent_name: str = "Clinical Reviewer Agent"
    checks_performed: list[AgentCheck] = []
    diagnosis_validation: list[DiagnosisValidation] = []
    procedure_validation: list[ProcedureValidation] = []
    clinical_extraction: ClinicalExtraction | None = None
    literature_support: list[LiteratureReference] = []
    clinical_trials: list[ClinicalTrialReference] = []
    clinical_summary: str = ""
    tool_results: list[ToolResult] = []
    error: str | None = None


class ProviderVerification(BaseModel):
    npi: str = ""
    name: str = ""
    specialty: str = ""
    status: str = ""  # "active", "inactive", "not_found"
    detail: str = ""


class CoveragePolicy(BaseModel):
    policy_id: str = ""
    title: str = ""
    type: str = ""  # "LCD", "NCD"
    relevant: bool = True


class CriterionAssessment(BaseModel):
    criterion: str = ""
    status: str = "INSUFFICIENT"  # "MET", "NOT_MET", "INSUFFICIENT"
    confidence: int = 0  # 0-100 per-criterion confidence
    evidence: list[str] = []
    notes: str = ""
    source: str = ""
    # Backward compat field
    met: bool = False


class DocumentationGap(BaseModel):
    what: str = ""
    critical: bool = False
    request: str = ""


class CoverageResult(BaseModel):
    agent_name: str = "Coverage Agent"
    checks_performed: list[AgentCheck] = []
    provider_verification: ProviderVerification | None = None
    coverage_policies: list[CoveragePolicy] = []
    criteria_assessment: list[CriterionAssessment] = []
    coverage_criteria_met: list[str] = []
    coverage_criteria_not_met: list[str] = []
    policy_references: list[str] = []
    coverage_limitations: list[str] = []
    documentation_gaps: list[DocumentationGap] = []
    tool_results: list[ToolResult] = []
    error: str | None = None


class SynthesisOutput(BaseModel):
    recommendation: str = "pend_for_review"  # "approve" or "pend_for_review"
    confidence: float = 0.0
    confidence_level: str = ""  # "HIGH", "MEDIUM", "LOW"
    summary: str = ""
    clinical_rationale: str = ""
    decision_gate: Literal["gate_1_provider", "gate_2_codes", "gate_3_necessity", "approved"] = "gate_3_necessity"
    coverage_criteria_met: list[str] = []
    coverage_criteria_not_met: list[str] = []
    missing_documentation: list[str] = []
    policy_references: list[str] = []
    criteria_summary: str = ""
    synthesis_audit_trail: str = ""  # JSON-encoded audit trail (dict not supported in structured output)
    disclaimer: str = ""


AGENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "compliance": ComplianceResult,
    "clinical": ClinicalResult,
    "coverage": CoverageResult,
    "synthesis": SynthesisOutput,
}
