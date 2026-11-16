"""Agent instructions (the Microsoft SKILL.md files).

Loaded from the MLflow Prompt Registry in Unity Catalog
(``<catalog>.<schema>.<agent>_skill@prod``) so clinical SMEs can version and
promote rule changes without a redeploy. Falls back to the SKILL.md files
shipped with the code.
"""
from __future__ import annotations

import functools
import logging
import os
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)

SKILL_DIRS = {
    "compliance": "compliance-review",
    "clinical": "clinical-review",
    "coverage": "coverage-assessment",
    "synthesis": "synthesis-decision",
}

AGENT_TITLES = {
    "compliance": "Compliance Validation Agent",
    "clinical": "Clinical Reviewer Agent",
    "coverage": "Coverage Assessment Agent",
    "synthesis": "Synthesis Decision Agent",
}

# Databricks-specific addendum for the Synthesis agent: in this design the
# three gates and the confidence formula run as deterministic Python
# (pa_core.gates). The agent writes the narrative around a fixed outcome.
SYNTHESIS_ADDENDUM = """
## DATABRICKS DEPLOYMENT OVERRIDE (takes precedence over the sections above)

In this deployment the gate evaluation and the weighted confidence formula are
computed by deterministic code BEFORE you run. The input contains
`deterministic_gates` with the authoritative values for: recommendation,
decision_gate, confidence, confidence_level, gate_results and
confidence_components.

- Copy recommendation, decision_gate, confidence and confidence_level exactly.
  Do not re-compute or change them.
- Put `deterministic_gates.synthesis_audit_trail` (JSON-encoded) in
  `synthesis_audit_trail` unchanged.
- Your job: write summary, clinical_rationale, criteria_summary,
  coverage_criteria_met / not_met, missing_documentation and policy_references,
  grounded only in the agent outputs, and explain WHY the gates came out as
  they did. If a gate result is driven by an UNKNOWN tool result, say that
  manual verification is required.
- The disclaimer is mandatory.
"""


def _skills_root() -> Path | None:
    candidates = [
        os.environ.get("PA_SKILLS_DIR", ""),
        str(Path(__file__).resolve().parent / "skills"),
        str(Path(__file__).resolve().parents[2] / "agents" / "skills"),
        str(Path.cwd() / "skills"),
    ]
    for c in candidates:
        if c and Path(c).is_dir():
            return Path(c)
    return None


def local_skill(agent_key: str) -> str:
    root = _skills_root()
    if root is None:
        raise FileNotFoundError("SKILL.md directory not found; set PA_SKILLS_DIR")
    text = (root / SKILL_DIRS[agent_key] / "SKILL.md").read_text(encoding="utf-8")
    # drop YAML front matter
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :].lstrip()
    return text


@functools.lru_cache(maxsize=8)
def skill_text(agent_key: str) -> tuple[str, str]:
    """Return (instructions, source) where source names the prompt version used."""
    s = get_settings()
    if s.use_prompt_registry:
        try:
            import mlflow

            mlflow.set_registry_uri("databricks-uc")
            uri = f"prompts:/{s.prompt_name(agent_key)}@{s.prompt_alias}"
            p = mlflow.genai.load_prompt(uri)
            return p.template, f"{s.prompt_name(agent_key)} v{p.version}"
        except Exception as e:  # noqa: BLE001
            logger.warning("Prompt Registry unavailable for %s (%s); using bundled SKILL.md", agent_key, e)
    return local_skill(agent_key), f"bundled SKILL.md ({SKILL_DIRS[agent_key]})"


def system_prompt(agent_key: str) -> tuple[str, str]:
    skill, source = skill_text(agent_key)
    intro = (
        f"You are the {AGENT_TITLES[agent_key]} in a prior authorization review pipeline "
        "running on Databricks. Follow the skill below exactly. The user message is a JSON "
        "payload with the case data. Use your tools when the skill calls for them. "
        "When finished, answer with ONLY the JSON object described by the output schema, "
        "no prose and no markdown fences.\n\n"
    )
    text = intro + skill
    if agent_key == "synthesis":
        text += "\n" + SYNTHESIS_ADDENDUM
    return text, source
