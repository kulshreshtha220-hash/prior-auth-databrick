"""Structured output schemas for the four agents.

Copied from the Microsoft accelerator (agents/*/schemas.py, MIT) and merged.
Every agent's final answer is validated against one of these models.
"""
from typing import Literal

from pydantic import BaseModel


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
