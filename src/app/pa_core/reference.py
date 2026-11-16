"""Reference-data adapters: versioned Delta snapshots used when a live MCP
server is unavailable (diagram: "MCP or adapter").

Tables are created by notebooks/01_setup_uc and refreshed by the
`pa_reference_refresh` job:
  ref_icd10cm(code, description, billable, code_set_version)
  ref_hcpcs(code, description, status, code_set_version)
  ref_cpt_common(code, description, category)      -- curated, CPT is AMA-licensed
  ref_ncd(ncd_id, title, indications, document_url, effective_date)
  ref_lcd(lcd_id, title, contractor, states, indications, document_url)
  ref_npi_cache(npi, name, taxonomy, taxonomy_desc, state, status, fetched_at)
"""
from __future__ import annotations

import re

from . import sql

ADAPTER_TOOLS: dict[str, list[dict]] = {
    "icd10_codes": [
        {
            "name": "ref_icd10_lookup",
            "description": "Look up ICD-10-CM codes in the versioned reference snapshot. "
            "Returns description and whether each code is billable.",
            "parameters": {
                "type": "object",
                "properties": {"codes": {"type": "array", "items": {"type": "string"}}},
                "required": ["codes"],
            },
        }
    ],
    "npi_registry": [
        {
            "name": "ref_npi_lookup",
            "description": "Look up a provider NPI in the cached NPPES snapshot (name, taxonomy, status).",
            "parameters": {
                "type": "object",
                "properties": {"npi": {"type": "string"}},
                "required": ["npi"],
            },
        }
    ],
    "cms_coverage": [
        {
            "name": "ref_coverage_search",
            "description": "Keyword search over the NCD and LCD reference snapshot. Returns policy ids, titles and indications.",
            "parameters": {
                "type": "object",
                "properties": {"keywords": {"type": "string"}},
                "required": ["keywords"],
            },
        }
    ],
}


def _clean_code(c: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(c).upper())


def call(tool: str, args: dict) -> dict:
    if tool == "ref_icd10_lookup":
        codes = [_clean_code(c) for c in args.get("codes", [])][:25]
        rows = sql.execute(
            f"SELECT code, description, billable, code_set_version FROM {sql.table('ref_icd10cm')} "
            "WHERE replace(code, '.', '') IN (SELECT explode(from_json(:codes, 'array<string>')))",
            {"codes": codes},
        )
        found = {_clean_code(r["code"]) for r in rows}
        return {"results": rows, "not_found": [c for c in codes if c not in found]}
    if tool == "ref_npi_lookup":
        npi = re.sub(r"\D", "", str(args.get("npi", "")))
        rows = sql.execute(
            f"SELECT * FROM {sql.table('ref_npi_cache')} WHERE npi = :npi LIMIT 1", {"npi": npi}
        )
        return {"result": rows[0] if rows else None, "note": "cached NPPES snapshot"}
    if tool == "ref_coverage_search":
        kw = str(args.get("keywords", ""))[:200]
        rows = sql.execute(
            "SELECT 'NCD' AS type, ncd_id AS policy_id, title, substr(indications, 1, 1500) AS indications, document_url "
            f"FROM {sql.table('ref_ncd')} WHERE lower(title) LIKE lower(concat('%', :kw, '%')) "
            "OR lower(indications) LIKE lower(concat('%', :kw, '%')) "
            "UNION ALL SELECT 'LCD', lcd_id, title, substr(indications, 1, 1500), document_url "
            f"FROM {sql.table('ref_lcd')} WHERE lower(title) LIKE lower(concat('%', :kw, '%')) "
            "OR lower(indications) LIKE lower(concat('%', :kw, '%')) LIMIT 10",
            {"kw": kw},
        )
        return {"results": rows}
    raise KeyError(tool)
