-- Unity Catalog data layer for Prior Authorization Review.
-- Run by notebooks/01_setup_uc with ${catalog} and ${schema} substituted.
-- Analytical record (written by the app through the SQL warehouse).

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.pa_requests (
  request_id STRING NOT NULL, provider_npi STRING, diagnosis_codes ARRAY<STRING>, procedure_codes ARRAY<STRING>,
  document_ids ARRAY<STRING>, submitted_by STRING, submitted_at TIMESTAMP, request_json VARIANT
) COMMENT 'Every PA request submitted to the review app (contains PHI)';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.documents (
  document_id STRING NOT NULL, filename STRING, volume_path STRING, pages INT, parsed_text STRING,
  parser STRING, uploaded_at TIMESTAMP
) COMMENT 'Uploaded referrals, notes, labs, imaging reports and their ai_parse_document text';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.agent_runs (
  request_id STRING, agent STRING, model STRING, prompt_version STRING, status STRING, duration_s DOUBLE,
  turns INT, tool_calls VARIANT, unavailable_sources VARIANT, created_at TIMESTAMP
) COMMENT 'One row per agent invocation: model, prompt version, tools used, UNKNOWN sources';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.agent_findings (
  request_id STRING, agent STRING, findings VARIANT, created_at TIMESTAMP
) COMMENT 'Full structured output of each agent';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.gate_results (
  request_id STRING, gate STRING, result STRING, reasons ARRAY<STRING>, recommendation STRING,
  confidence DOUBLE, created_at TIMESTAMP
) COMMENT 'Deterministic gate outcomes (PASS / FAIL / NOT_EVALUATED) with reasons';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.final_decisions (
  request_id STRING, authorization_number STRING, final_recommendation STRING, was_overridden BOOLEAN,
  override_rationale STRING, decided_by STRING, decided_at TIMESTAMP, letter_pdf_path STRING
) COMMENT 'Human reviewer decisions (accept / override) and letter location';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.audit_events (
  request_id STRING, event_type STRING, actor STRING, event_data VARIANT, created_at TIMESTAMP
) COMMENT 'Append-only audit log mirrored from Lakebase pa.audit_events';

-- Reference data (versioned snapshots, refreshed by the pa_reference_refresh job)
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.ref_icd10cm (
  code STRING, description STRING, billable BOOLEAN, code_set_version STRING, loaded_at TIMESTAMP
) TBLPROPERTIES (delta.enableChangeDataFeed = true);

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.ref_hcpcs (
  code STRING, description STRING, status STRING, code_set_version STRING, loaded_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.ref_cpt_common (
  code STRING, description STRING, category STRING, loaded_at TIMESTAMP
) COMMENT 'Curated PA-trigger CPT codes (CPT is AMA-licensed; load your licensed file here if you have one)';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.ref_ncd (
  ncd_id STRING, title STRING, indications STRING, document_url STRING, effective_date STRING, loaded_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.ref_lcd (
  lcd_id STRING, title STRING, contractor STRING, states STRING, indications STRING, document_url STRING,
  loaded_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.ref_npi_cache (
  npi STRING, name STRING, taxonomy STRING, taxonomy_desc STRING, state STRING, status STRING, fetched_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.eval_cases (
  case_id STRING, request_json VARIANT, expected_recommendation STRING, expected_gate STRING, source STRING,
  added_at TIMESTAMP
) COMMENT 'Labelled cases for batch evaluation (seed + reviewer overrides)';
