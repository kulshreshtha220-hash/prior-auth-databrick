"""Multi-Agent Orchestrator for Prior Authorization Review.

Coordinates three specialized agents in a fan-out/fan-in pattern:
  Phase 1 (parallel): Compliance Agent + Clinical Reviewer Agent
  Phase 2 (sequential): Coverage Agent (receives clinical findings)
  Phase 3: Synthesis — aggregates all agent outputs into a final decision

Enhanced with the Anthropic prior-auth-review-skill decision rubric:
  - LENIENT mode (default): all problematic scenarios -> PEND
  - Structured evaluation order: provider -> codes -> med necessity
  - Confidence scoring: HIGH/MEDIUM/LOW + 0-100
  - Audit trail with data sources and metrics
  - Audit justification document generation

Databricks port: the four agents run as MLflow ResponsesAgent endpoints on
Model Serving. The pipeline is a LangGraph graph checkpointed in Lakebase
(idempotent per request_id), and the three gates + confidence formula run as
deterministic Python (pa_core.gates) before the Synthesis agent writes the
narrative.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from app.agents.compliance_agent import run_compliance_review
from app.agents.clinical_agent import run_clinical_review
from app.agents.coverage_agent import run_coverage_review
from app.agents.synthesis_agent import run_synthesis_review as _dispatch_synthesis
from app.services.audit_pdf import generate_audit_justification_pdf
from app.services.cpt_validation import validate_procedure_codes

logger = logging.getLogger(__name__)

from contextlib import contextmanager


@contextmanager
def _span(name: str, **attrs):
    """MLflow trace span when MLflow is available; no-op otherwise."""
    try:
        import mlflow

        with mlflow.start_span(name=name) as span:
            if attrs:
                span.set_attributes(attrs)
            yield span
    except ImportError:
        yield None


# Maximum number of retries when an agent returns an incomplete result
_MAX_AGENT_RETRIES = 1

# Expected top-level keys for each agent result.
# If any of these are missing the result is considered incomplete/truncated.
_EXPECTED_KEYS: dict[str, set[str]] = {
    "Compliance Agent": {"checklist", "overall_status"},
    "Clinical Reviewer Agent": {
        "diagnosis_validation",
        "clinical_extraction",
        "clinical_summary",
    },
    "Coverage Agent": {"provider_verification", "criteria_assessment"},
    "Synthesis Agent": {"summary", "disclaimer"},
}


def _validate_agent_result(agent_name: str, result: dict) -> list[str]:
    """Check that an agent result contains the expected top-level keys.

    Returns a list of missing key names (empty list means valid).
    """
    if result.get("error"):
        return [f"error: {result['error']}"]

    expected = _EXPECTED_KEYS.get(agent_name, set())
    if not expected:
        return []

    missing = [k for k in expected if k not in result]
    return missing


_AGENT_DISPLAY_NAMES: dict[str, str] = {
    "compliance": "Compliance Agent",
    "clinical": "Clinical Reviewer Agent",
    "coverage": "Coverage Assessment Agent",
}

_CHECKLIST_STATUS_MAP: dict[str, str] = {
    "complete": "pass",
    "incomplete": "warning",
    "missing": "fail",
}


def _enrich_agent_result(agent_key: str, result: dict) -> dict:
    """Inject ``agent_name`` and ``checks_performed`` into an agent result dict.

    The frontend's AgentDetails component expects both fields on every
    agent result.  Since the hosted agents do not emit them (they are not
    part of the SKILL.md output schemas), we derive them here:

    - ``agent_name``      — human-readable display name for the agent.
    - ``checks_performed`` — for compliance: mapped from the ``checklist``
      items (complete→pass, incomplete→warning, missing→fail);
      for clinical/coverage: mapped from ``tool_results``
      (tool_name→rule, status→result, detail kept as-is).
    """
    if not result or result.get("error"):
        return result

    enriched = dict(result)
    enriched.setdefault("agent_name", _AGENT_DISPLAY_NAMES.get(agent_key, agent_key))

    if "checks_performed" not in enriched:
        if agent_key == "compliance":
            # Derive from checklist (compliance has no tool_results)
            checks_performed = [
                {
                    "rule": item.get("item", ""),
                    "result": _CHECKLIST_STATUS_MAP.get(item.get("status", ""), "info"),
                    "detail": item.get("detail", ""),
                }
                for item in enriched.get("checklist", [])
            ]
        else:
            # Derive from tool_results (clinical + coverage)
            checks_performed = [
                {
                    "rule": tr.get("tool_name", ""),
                    "result": tr.get("status", "info"),
                    "detail": tr.get("detail", ""),
                }
                for tr in enriched.get("tool_results", [])
            ]
        enriched["checks_performed"] = checks_performed

    return enriched


# --- Persistence: Lakebase + UC Volume + Delta (see app/services/store.py) ---
from app.services.store import (  # noqa: E402,F401  (re-exported for the routers)
    get_review,
    list_reviews,
    store_decision,
    store_review,
)


def _compute_confidence(
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
) -> tuple[float, str]:
    """Compute overall confidence score and level from agent results."""
    scores = []

    # Extraction confidence from clinical agent
    extraction = clinical_result.get("clinical_extraction", {})
    if isinstance(extraction, dict):
        ext_conf = extraction.get("extraction_confidence", 50)
        scores.append(ext_conf / 100.0)

    # Per-criterion confidence from coverage agent
    criteria = coverage_result.get("criteria_assessment", [])
    if criteria:
        criterion_scores = [
            c.get("confidence", 50) / 100.0
            for c in criteria
            if isinstance(c, dict)
        ]
        if criterion_scores:
            scores.append(sum(criterion_scores) / len(criterion_scores))

    # Compliance completeness bonus/penalty
    compliance_status = compliance_result.get("overall_status", "incomplete")
    missing = compliance_result.get("missing_items", [])
    if compliance_status == "complete" and not missing:
        scores.append(1.0)
    else:
        penalty = max(0.0, 1.0 - 0.1 * len(missing))
        scores.append(penalty)

    # Agent error penalties
    for result in [compliance_result, clinical_result, coverage_result]:
        if result.get("error"):
            scores.append(0.0)

    if not scores:
        return 0.5, "MEDIUM"

    confidence = sum(scores) / len(scores)
    confidence = max(0.0, min(1.0, confidence))

    if confidence >= 0.80:
        level = "HIGH"
    elif confidence >= 0.50:
        level = "MEDIUM"
    else:
        level = "LOW"

    return round(confidence, 2), level


def _normalize_coverage_result(coverage_result: dict) -> dict:
    """Lightweight pass-through for coverage agent output.

    With structured output (output_format), the coverage agent returns data
    matching the CoverageResult Pydantic schema directly. This function
    only normalizes the provider_verification status field for display
    consistency (e.g., 'A' -> 'VERIFIED').
    """
    if coverage_result.get("error"):
        return coverage_result

    result = dict(coverage_result)

    # Normalize provider_verification status for display
    pv = result.get("provider_verification")
    if pv and isinstance(pv, dict):
        status = str(pv.get("status", "")).upper()
        if status in ("A", "ACTIVE", "VERIFIED"):
            pv["status"] = "VERIFIED"
        elif status in ("D", "DEACTIVATED", "INACTIVE"):
            pv["status"] = "INACTIVE"

    return result


def _build_audit_trail(
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    start_time: str,
    synthesis: dict | None = None,
) -> dict:
    """Build audit trail from agent results."""
    data_sources = ["CPT/HCPCS Format Validation (Local)"]

    # Check which MCP tools were used via tool_results
    for result in [clinical_result, coverage_result]:
        for tr in result.get("tool_results", []):
            tool = tr.get("tool_name", "")
            tool_lower = tool.lower()
            if "npi" in tool_lower:
                source = "NPI Registry MCP (NPPES)"
            elif "icd10" in tool_lower or "icd-10" in tool_lower or "validate_code" in tool_lower or "lookup_code" in tool_lower:
                source = "ICD-10 MCP (2026 Code Set)"
            elif "coverage" in tool_lower or "cms" in tool_lower or "lcd" in tool_lower or "ncd" in tool_lower:
                source = "CMS Coverage MCP (LCDs/NCDs)"
            elif "trial" in tool_lower or "clinical_trial" in tool_lower or "clinical-trial" in tool_lower:
                source = "ClinicalTrials.gov MCP"
            elif "pubmed" in tool_lower:
                source = "PubMed MCP (Biomedical Literature)"
            elif "search" in tool_lower:
                # Generic "search" — likely PubMed search
                source = "PubMed MCP (Biomedical Literature)"
            else:
                source = f"MCP Tool: {tool}"
            if source not in data_sources:
                data_sources.append(source)

    # Always infer data sources from result data to supplement tool_results
    # (agents may not always report tool_results for every MCP call)

    # If provider verification has data, NPI registry was used
    pv = coverage_result.get("provider_verification", {})
    if pv and isinstance(pv, dict) and pv.get("npi"):
        if "NPI Registry MCP (NPPES)" not in data_sources:
            data_sources.append("NPI Registry MCP (NPPES)")

    # If diagnosis validation has data, ICD-10 MCP was used
    dx = clinical_result.get("diagnosis_validation", [])
    if dx:
        if "ICD-10 MCP (2026 Code Set)" not in data_sources:
            data_sources.append("ICD-10 MCP (2026 Code Set)")

    # If coverage policies found, CMS Coverage MCP was used
    policies = coverage_result.get("coverage_policies", [])
    if policies:
        if "CMS Coverage MCP (LCDs/NCDs)" not in data_sources:
            data_sources.append("CMS Coverage MCP (LCDs/NCDs)")

    # If literature support found, PubMed was used
    lit = clinical_result.get("literature_support", [])
    if lit:
        if "PubMed MCP (Biomedical Literature)" not in data_sources:
            data_sources.append("PubMed MCP (Biomedical Literature)")

    # If clinical trials found, ClinicalTrials.gov was used
    trials = clinical_result.get("clinical_trials", [])
    if trials:
        if "ClinicalTrials.gov MCP" not in data_sources:
            data_sources.append("ClinicalTrials.gov MCP")

    # Ensure all 5 MCP data sources are always listed — all servers are
    # queried on every review run, even if they return zero results
    for source in [
        "NPI Registry MCP (NPPES)",
        "ICD-10 MCP (2026 Code Set)",
        "CMS Coverage MCP (LCDs/NCDs)",
        "PubMed MCP (Biomedical Literature)",
        "ClinicalTrials.gov MCP",
    ]:
        if source not in data_sources:
            data_sources.append(source)

    # Extraction confidence
    extraction = clinical_result.get("clinical_extraction", {})
    ext_conf = extraction.get("extraction_confidence", 0) if isinstance(extraction, dict) else 0

    # Assessment confidence (avg of criterion confidences)
    criteria = coverage_result.get("criteria_assessment", [])

    # If coverage agent didn't provide criteria, try synthesis
    if not criteria and synthesis:
        criteria = synthesis.get("criteria_assessment", [])

    if criteria:
        conf_scores = [c.get("confidence", 0) for c in criteria if isinstance(c, dict)]
        assess_conf = int(sum(conf_scores) / len(conf_scores)) if conf_scores else 0
    else:
        assess_conf = 0

    # Criteria met count (case-insensitive — agents may return lowercase)
    met = sum(1 for c in criteria if isinstance(c, dict) and str(c.get("status", "")).upper() == "MET")
    total = len(criteria)
    criteria_met_count = f"{met}/{total}" if total else "0/0"

    # If criteria_met_count is 0/0 but synthesis has criteria data, use it
    if criteria_met_count == "0/0" and synthesis:
        syn_met = synthesis.get("coverage_criteria_met", [])
        syn_not_met = synthesis.get("coverage_criteria_not_met", [])
        if syn_met or syn_not_met:
            criteria_met_count = f"{len(syn_met)}/{len(syn_met) + len(syn_not_met)}"
            if assess_conf == 0 and syn_met:
                # Estimate from synthesis confidence
                assess_conf = int(synthesis.get("confidence", 0.5) * 100)

    return {
        "data_sources": data_sources,
        "review_started": start_time,
        "review_completed": datetime.now(timezone.utc).isoformat(),
        "extraction_confidence": ext_conf,
        "assessment_confidence": assess_conf,
        "criteria_met_count": criteria_met_count,
    }


def _generate_audit_justification(
    request_data: dict,
    synthesis: dict,
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    audit_trail: dict,
) -> str:
    """Generate an audit justification document in Markdown format.

    Based on the Anthropic prior-auth-review-skill audit_justification.md template.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recommendation = str(synthesis.get("recommendation", "pend_for_review")).upper()
    confidence = synthesis.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (ValueError, TypeError):
        confidence = 0.0
    confidence_level = synthesis.get("confidence_level", "LOW")

    lines = []

    # --- Disclaimer Header ---
    lines.append("# Prior Authorization Review — Audit Justification")
    lines.append("")
    lines.append("> **WARNING: AI-ASSISTED DRAFT — REVIEW REQUIRED**")
    lines.append("> All recommendations are drafts requiring human clinical review.")
    lines.append("> Coverage policies reflect Medicare LCDs/NCDs only.")
    lines.append("> Commercial and Medicare Advantage plans may differ.")
    lines.append("")

    # --- Section 1: Executive Summary ---
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(f"- **Review Date:** {now}")
    lines.append(f"- **Patient:** {request_data.get('patient_name', 'N/A')} (DOB: {request_data.get('patient_dob', 'N/A')})")
    lines.append(f"- **Provider NPI:** {request_data.get('provider_npi', 'N/A')}")
    lines.append(f"- **Insurance ID:** {request_data.get('insurance_id') or 'Not provided'}")
    lines.append(f"- **Diagnosis Codes:** {', '.join(request_data.get('diagnosis_codes', []))}")
    lines.append(f"- **Procedure Codes:** {', '.join(request_data.get('procedure_codes', []))}")
    lines.append(f"- **Decision:** {recommendation}")
    lines.append(f"- **Confidence:** {confidence_level} ({int(confidence * 100)}%)")
    lines.append("")
    lines.append(f"**Summary:** {synthesis.get('summary', 'N/A')}")
    lines.append("")

    # --- Section 2: Medical Necessity Assessment ---
    lines.append("## 2. Medical Necessity Assessment")
    lines.append("")

    # Coverage policy
    pv = coverage_result.get("provider_verification", {})
    if pv and isinstance(pv, dict):
        lines.append(f"**Provider:** {pv.get('name', 'N/A')} — {pv.get('specialty', 'N/A')} — Status: {pv.get('status', 'N/A')}")
        lines.append("")

    policies = coverage_result.get("coverage_policies", [])
    if policies:
        lines.append("**Coverage Policies Applied:**")
        for p in policies:
            if isinstance(p, dict):
                lines.append(f"- {p.get('policy_id', '?')}: {p.get('title', 'N/A')} ({p.get('type', '?')})")
        lines.append("")

    # Clinical evidence summary
    extraction = clinical_result.get("clinical_extraction", {})
    if isinstance(extraction, dict):
        lines.append("**Clinical Evidence Summary:**")
        if extraction.get("chief_complaint"):
            lines.append(f"- Chief Complaint: {extraction['chief_complaint']}")
        if extraction.get("prior_treatments"):
            lines.append(f"- Prior Treatments: {'; '.join(str(t) for t in extraction['prior_treatments'][:5])}")
        if extraction.get("severity_indicators"):
            lines.append(f"- Severity Indicators: {'; '.join(str(i) for i in extraction['severity_indicators'][:5])}")
        lines.append(f"- Extraction Confidence: {extraction.get('extraction_confidence', 0)}%")
        lines.append("")

    # --- Section 3: Criterion-by-Criterion Evaluation ---
    lines.append("## 3. Criterion-by-Criterion Evaluation")
    lines.append("")

    criteria = coverage_result.get("criteria_assessment", [])
    if criteria:
        lines.append(f"**Criteria Met:** {audit_trail.get('criteria_met_count', '0/0')}")
        lines.append("")
        for c in criteria:
            if not isinstance(c, dict):
                continue
            status = c.get("status", "INSUFFICIENT")
            icon = {"MET": "PASS", "NOT_MET": "FAIL", "INSUFFICIENT": "INFO"}.get(status, "?")
            lines.append(f"### [{icon}] {c.get('criterion', 'N/A')}")
            lines.append(f"- **Status:** {status}")
            lines.append(f"- **Confidence:** {c.get('confidence', 0)}%")
            evidence = c.get("evidence", [])
            if isinstance(evidence, list) and evidence:
                lines.append("- **Evidence:**")
                for e in evidence:
                    lines.append(f"  - {str(e)}")
            elif isinstance(evidence, str) and evidence:
                lines.append(f"- **Evidence:** {evidence}")
            if c.get("notes"):
                lines.append(f"- **Notes:** {c['notes']}")
            lines.append("")
    else:
        lines.append("No coverage criteria were identified for evaluation.")
        lines.append("")

    # --- Section 4: Validation Checks ---
    lines.append("## 4. Validation Checks")
    lines.append("")

    # Provider verification
    if pv and isinstance(pv, dict):
        lines.append(f"**Provider Verification:** NPI {pv.get('npi', 'N/A')} — {pv.get('status', 'N/A')}")
        if pv.get("detail"):
            lines.append(f"  Detail: {pv['detail']}")
        lines.append("")

    # Diagnosis code validation
    dx_val = clinical_result.get("diagnosis_validation", [])
    if dx_val:
        lines.append("**Diagnosis Code Validation:**")
        lines.append("")
        lines.append("| Code | Description | Billable | Valid |")
        lines.append("|------|-------------|----------|------|")
        for d in dx_val:
            if isinstance(d, dict):
                code = d.get("code", "?")
                desc = d.get("description", "N/A")[:60]
                billable = "Yes" if d.get("billable") else "No"
                valid = "Yes" if d.get("valid") else "No"
                lines.append(f"| {code} | {desc} | {billable} | {valid} |")
        lines.append("")

    # Compliance checklist
    checklist = compliance_result.get("checklist", [])
    if checklist:
        lines.append("**Compliance Checklist:**")
        lines.append("")
        lines.append("| Item | Status | Detail |")
        lines.append("|------|--------|--------|")
        for item in checklist:
            if isinstance(item, dict):
                lines.append(f"| {item.get('item', '?')} | {item.get('status', '?')} | {item.get('detail', '')[:60]} |")
        lines.append("")

    # --- Section 5: Decision Rationale ---
    lines.append("## 5. Decision Rationale")
    lines.append("")
    lines.append(f"**Decision:** {recommendation}")
    # Render decision gates — field may contain pipe-separated gates
    gate_raw = synthesis.get("decision_gate", "N/A")
    gate_parts = [g.strip() for g in str(gate_raw).split("|") if g.strip()]
    if len(gate_parts) > 1:
        lines.append("")
        lines.append("**Decision Gates:**")
        for gp in gate_parts:
            # Extract gate label (e.g. "GATE 1 (Provider)") and result
            if ": PASS" in gp.upper():
                lines.append(f"- [PASS] {gp}")
            elif ": FAIL" in gp.upper():
                lines.append(f"- [FAIL] {gp}")
            else:
                lines.append(f"- {gp}")
    else:
        lines.append(f"**Gate:** {gate_raw}")
    lines.append(f"**Confidence:** {confidence_level} ({int(confidence * 100)}%)")
    lines.append("")
    lines.append(synthesis.get("clinical_rationale", "No rationale provided."))
    lines.append("")

    # Supporting facts
    met_criteria = synthesis.get("coverage_criteria_met", [])
    if met_criteria:
        lines.append("**Key Supporting Facts:**")
        for m in met_criteria:
            lines.append(f"- {str(m)}")
        lines.append("")

    # --- Section 6: Documentation Gaps ---
    gaps = coverage_result.get("documentation_gaps", [])
    if gaps:
        lines.append("## 6. Documentation Gaps")
        lines.append("")
        for g in gaps:
            if isinstance(g, dict):
                critical = "CRITICAL" if g.get("critical") else "Non-critical"
                lines.append(f"- [{critical}] {g.get('what', g.get('description', 'N/A'))}")
                if g.get("request"):
                    lines.append(f"  Request: {g['request']}")
            else:
                lines.append(f"- {str(g)}")
        lines.append("")

    # --- Section 7: Audit Trail ---
    lines.append("## 7. Audit Trail")
    lines.append("")
    lines.append("**Data Sources:**")
    for src in audit_trail.get("data_sources", []):
        lines.append(f"- {src}")
    lines.append("")
    lines.append(f"- Review Started: {audit_trail.get('review_started', 'N/A')}")
    lines.append(f"- Review Completed: {audit_trail.get('review_completed', 'N/A')}")
    lines.append(f"- Extraction Confidence: {audit_trail.get('extraction_confidence', 0)}%")
    lines.append(f"- Assessment Confidence: {audit_trail.get('assessment_confidence', 0)}%")
    lines.append(f"- Criteria Met: {audit_trail.get('criteria_met_count', '0/0')}")
    lines.append("")

    # --- Section 8: Regulatory Compliance ---
    lines.append("## 8. Regulatory Compliance")
    lines.append("")
    lines.append("**Decision Policy:** LENIENT Mode (default)")
    lines.append("- Provider verification: Required")
    lines.append("- Code validation: Required")
    lines.append("- Medical necessity criteria: All must be MET for approval")
    lines.append("- Unmet/insufficient criteria: Results in PEND (not DENY)")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated: {now} | AI-Assisted Prior Authorization Review System*")

    return "\n".join(lines)




# =============================================================================
# LangGraph pipeline (Databricks port)
#
#   preflight ──┬─> compliance ─┐
#               └─> clinical  ──┴─> coverage ─> gates (Python) ─> synthesis ─> audit
#
# Checkpointed per request_id (thread_id) in Lakebase: a review interrupted by
# an app restart resumes from the last finished node, and a finished review is
# returned as-is instead of calling the agents again (idempotent run key).
# =============================================================================
from typing import TypedDict  # noqa: E402

from pa_core import gates as pa_gates  # noqa: E402
from pa_core.config import get_settings  # noqa: E402

from app.services import store as _store  # noqa: E402

_progress_callbacks: dict[str, Callable[[dict], Awaitable[None]]] = {}


class ReviewState(TypedDict, total=False):
    request_id: str
    request_data: dict
    start_time: str
    cpt_validation: dict
    compliance: dict
    clinical: dict
    coverage: dict
    gates: dict
    synthesis: dict
    result: dict


async def _emit(state: ReviewState, event: dict) -> None:
    rid = state.get("request_id", "")
    cb = _progress_callbacks.get(rid)
    if cb:
        await cb(event)
    await asyncio.to_thread(_store.update_progress, rid, event.get("phase", ""), int(event.get("progress_pct", 0)))


def _agent_status(name: str, result: dict, ok_msg: str) -> dict:
    if result.get("error") or result.get("_error"):
        return {"status": "error", "detail": result.get("error") or result.get("_error")}
    missing = _validate_agent_result(name, result)
    if missing:
        return {"status": "warning", "detail": f"Partial result - missing: {', '.join(missing)}"}
    return {"status": "done", "detail": ok_msg}


async def _safe_run(agent_name: str, fn, *args, **kwargs) -> dict:
    """Run an agent with one retry when its result is incomplete (as in Microsoft's design)."""
    last: dict = {"error": "Agent did not run", "tool_results": []}
    for attempt in range(_MAX_AGENT_RETRIES + 1):
        last = await fn(*args, **kwargs)
        missing = _validate_agent_result(agent_name, last)
        if not missing:
            return last
        logger.warning("%s incomplete (attempt %d): %s", agent_name, attempt + 1, missing)
    return last


# ---------------------------------------------------------------- nodes
async def node_preflight(state: ReviewState) -> dict:
    with _span("preflight"):
        cpt = validate_procedure_codes(state["request_data"].get("procedure_codes", []))
    await _emit(state, {"phase": "preflight", "status": "completed", "progress_pct": 5,
                        "message": "CPT/HCPCS format validation complete", "agents": {}})
    await _emit(state, {"phase": "phase_1", "status": "running", "progress_pct": 10,
                        "message": "Running Compliance and Clinical agents in parallel",
                        "agents": {"compliance": {"status": "running", "detail": "Checking documentation completeness"},
                                   "clinical": {"status": "running", "detail": "Validating codes and extracting clinical evidence"}}})
    return {"cpt_validation": cpt, "start_time": datetime.now(timezone.utc).isoformat()}


async def node_compliance(state: ReviewState) -> dict:
    with _span("agent_compliance"):
        res = await _safe_run("Compliance Agent", run_compliance_review, state["request_data"])
    return {"compliance": res}


async def node_clinical(state: ReviewState) -> dict:
    req = {**state["request_data"], "cpt_preflight": state["cpt_validation"]}
    with _span("agent_clinical"):
        res = await _safe_run("Clinical Reviewer Agent", run_clinical_review, req)
    return {"clinical": res}


async def node_coverage(state: ReviewState) -> dict:
    await _emit(state, {"phase": "phase_1", "status": "completed", "progress_pct": 40,
                        "message": "Compliance and Clinical agents completed",
                        "agents": {"compliance": _agent_status("Compliance Agent", state["compliance"], "Documentation review complete"),
                                   "clinical": _agent_status("Clinical Reviewer Agent", state["clinical"], "Clinical analysis complete")}})
    await _emit(state, {"phase": "phase_2", "status": "running", "progress_pct": 45,
                        "message": "Running Coverage Agent with clinical findings",
                        "agents": {"coverage": {"status": "running", "detail": "Verifying provider and assessing coverage criteria"}}})
    clinical_for_coverage = {k: v for k, v in state["clinical"].items() if k != "_meta"}
    with _span("agent_coverage"):
        res = await _safe_run("Coverage Agent", run_coverage_review, state["request_data"], clinical_for_coverage)
    res = _normalize_coverage_result(res)
    await _emit(state, {"phase": "phase_2", "status": "completed", "progress_pct": 70, "message": "Coverage Agent completed",
                        "agents": {"coverage": _agent_status("Coverage Agent", res, "Coverage analysis complete")}})
    return {"coverage": res}


async def node_gates(state: ReviewState) -> dict:
    await _emit(state, {"phase": "phase_3", "status": "running", "progress_pct": 75,
                        "message": "Applying decision gates and synthesizing recommendation",
                        "agents": {"synthesis": {"status": "running", "detail": "Gate 1 provider, Gate 2 codes, Gate 3 necessity"}}})
    with _span("deterministic_gates") as sp:
        outcome = pa_gates.evaluate(state["compliance"], state["clinical"], state["coverage"], state["cpt_validation"]).to_dict()
        if sp is not None:
            sp.set_attributes({"recommendation": outcome["recommendation"], "decision_gate": outcome["decision_gate"],
                               "confidence": outcome["confidence"]})
    return {"gates": outcome}


def _fallback_synthesis(g: dict, coverage: dict, compliance: dict) -> dict:
    reasons = [r for rs in g["gate_reasons"].values() for r in rs]
    met = [c.get("criterion", "") for c in coverage.get("criteria_assessment") or [] if str(c.get("status")).upper() == "MET"]
    total = len(coverage.get("criteria_assessment") or [])
    return {
        "summary": ("All three gates passed." if g["recommendation"] == pa_gates.APPROVE
                    else f"Pended at {g['decision_gate']}: " + "; ".join(reasons[:3])),
        "clinical_rationale": "; ".join(reasons) or "All gates passed.",
        "coverage_criteria_met": met,
        "coverage_criteria_not_met": list(coverage.get("coverage_criteria_not_met") or []),
        "missing_documentation": list(compliance.get("missing_items") or []),
        "policy_references": list(coverage.get("policy_references") or []),
        "criteria_summary": f"{len(met)} of {total} criteria MET",
        "disclaimer": ("AI-assisted draft. Coverage policies reflect Medicare LCDs/NCDs only. Commercial and Medicare "
                       "Advantage plans may differ. Human clinical review required before final determination."),
    }


async def node_synthesis(state: ReviewState) -> dict:
    g = state["gates"]
    with _span("agent_synthesis"):
        syn = await _safe_run("Synthesis Agent", _dispatch_synthesis, state["request_data"], state["compliance"],
                              state["clinical"], state["coverage"], state["cpt_validation"], g)
    if syn.get("error") or syn.get("_error") or not syn.get("summary"):
        logger.warning("Synthesis agent unavailable; using deterministic narrative")
        syn = {**_fallback_synthesis(g, state["coverage"], state["compliance"]),
               "synthesis_agent_error": syn.get("error") or syn.get("_error")}
    # Deterministic gates are authoritative.
    for k in ("recommendation", "decision_gate", "confidence", "confidence_level"):
        if syn.get(k) not in (None, "") and syn.get(k) != g[k]:
            logger.info("Synthesis agent proposed %s=%r; keeping gate value %r", k, syn.get(k), g[k])
        syn[k] = g[k]
    syn["synthesis_audit_trail"] = g["synthesis_audit_trail"]
    for key in ("coverage_criteria_met", "coverage_criteria_not_met", "missing_documentation", "policy_references"):
        val = syn.get(key)
        syn[key] = [str(i) if not isinstance(i, str) else i for i in val] if isinstance(val, list) else []
    syn.setdefault("disclaimer", _fallback_synthesis(g, state["coverage"], state["compliance"])["disclaimer"])
    syn.pop("_meta", None)
    await _emit(state, {"phase": "phase_3", "status": "completed", "progress_pct": 90, "message": "Synthesis complete",
                        "agents": {"synthesis": {"status": "done", "detail": f"{g['recommendation']} at {g['decision_gate']}"}}})
    return {"synthesis": syn}


_STATUS_MAP = {"success": "pass", "completed": "pass", "found": "pass", "verified": "pass", "valid": "pass", "ok": "pass",
               "error": "fail", "failed": "fail", "invalid": "fail", "not_found": "warning", "partial": "warning",
               "info": "warning", "unknown": "warning"}


def _normalize_tool_result(tr: dict) -> dict:
    raw = str(tr.get("status", "warning")).lower().strip()
    return {"tool_name": tr.get("tool_name", "unknown"), "status": _STATUS_MAP.get(raw, raw), "detail": tr.get("detail", "")}


async def node_audit(state: ReviewState) -> dict:
    await _emit(state, {"phase": "phase_4", "status": "running", "progress_pct": 92,
                        "message": "Building audit trail and justification document", "agents": {}})
    req, cpt = state["request_data"], state["cpt_validation"]
    compliance, clinical, coverage, synthesis = state["compliance"], state["clinical"], state["coverage"], state["synthesis"]
    with _span("audit"):
        audit_trail = _build_audit_trail(compliance, clinical, coverage, state["start_time"], synthesis=synthesis)
        audit_trail["agent_runs"] = {k: (r or {}).get("_meta", {}) for k, r in
                                     (("compliance", compliance), ("clinical", clinical), ("coverage", coverage))}
        justification = _generate_audit_justification(req, synthesis, compliance, clinical, coverage, audit_trail)
        try:
            pdf = generate_audit_justification_pdf(req, synthesis, compliance, clinical, coverage, audit_trail)
        except Exception as e:  # noqa: BLE001
            logger.error("Audit PDF generation failed: %s", e)
            pdf = None

    tools = [{"tool_name": "cpt_format_validation", "status": "pass" if cpt["valid"] else "fail", "detail": cpt["summary"]}]
    for r in (clinical, coverage):
        tools += [_normalize_tool_result(t) for t in r.get("tool_results", []) if isinstance(t, dict)]
    existing = {t["tool_name"].lower() for t in tools}
    dx = clinical.get("diagnosis_validation") or []
    if dx and not any("icd" in t or "diagnosis" in t for t in existing):
        ok = sum(1 for d in dx if isinstance(d, dict) and d.get("valid"))
        tools.append({"tool_name": "icd10_validation", "status": "pass" if ok == len(dx) else "warning",
                      "detail": f"{ok}/{len(dx)} codes valid"})

    result = {
        **synthesis,
        "tool_results": tools,
        "agent_results": {"compliance": _enrich_agent_result("compliance", compliance),
                          "clinical": _enrich_agent_result("clinical", clinical),
                          "coverage": _enrich_agent_result("coverage", coverage)},
        "audit_trail": audit_trail,
        "audit_justification": justification,
        "audit_justification_pdf": pdf,
    }
    await asyncio.to_thread(_store.record_agent_outputs, state["request_id"],
                            {"compliance": compliance, "clinical": clinical, "coverage": coverage}, state["gates"])
    await _emit(state, {"phase": "phase_4", "status": "completed", "progress_pct": 100, "message": "Review complete", "agents": {}})
    return {"result": result}


# ---------------------------------------------------------------- graph
_graph = None
_checkpointer_ready = False


def _build_graph(checkpointer):
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(ReviewState)
    g.add_node("preflight", node_preflight)
    g.add_node("compliance", node_compliance)
    g.add_node("clinical", node_clinical)
    g.add_node("coverage", node_coverage)
    g.add_node("gates", node_gates)
    g.add_node("synthesis", node_synthesis)
    g.add_node("audit", node_audit)
    g.add_edge(START, "preflight")
    g.add_edge("preflight", "compliance")
    g.add_edge("preflight", "clinical")
    g.add_edge(["compliance", "clinical"], "coverage")
    g.add_edge("coverage", "gates")
    g.add_edge("gates", "synthesis")
    g.add_edge("synthesis", "audit")
    g.add_edge("audit", END)
    return g.compile(checkpointer=checkpointer)


async def _get_graph():
    global _graph
    if _graph is not None:
        return _graph
    checkpointer = None
    if get_settings().state_store == "lakebase":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            from app.services.lakebase import async_pool

            checkpointer = AsyncPostgresSaver(await async_pool())
            await checkpointer.setup()
        except Exception as e:  # noqa: BLE001
            logger.warning("Lakebase checkpointer unavailable (%s); using in-memory checkpoints", e)
            checkpointer = None
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
    _graph = _build_graph(checkpointer)
    return _graph


async def run_multi_agent_review(
    request_data: dict,
    on_progress: Callable[[dict], Awaitable[None]] | None = None,
    request_id: str | None = None,
) -> dict:
    """Run the review graph. Same contract as Microsoft's function, plus request_id."""
    import uuid

    rid = request_id or request_data.get("request_id") or str(uuid.uuid4())
    if on_progress:
        _progress_callbacks[rid] = on_progress
    graph = await _get_graph()
    config = {"configurable": {"thread_id": rid}, "recursion_limit": 30}
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.values.get("result") and not snapshot.next:
            logger.info("Review %s already completed; returning checkpointed result", rid)
            return snapshot.values["result"]
        resume = bool(snapshot and snapshot.next)
        with _span("prior_auth_review", request_id=rid, resumed=resume):
            final = await graph.ainvoke(
                None if resume else {"request_id": rid, "request_data": request_data}, config=config
            )
        return final["result"]
    finally:
        _progress_callbacks.pop(rid, None)
