#!/usr/bin/env bash
# Register the 5 Anthropic healthcare MCP servers as Unity Gateway MCP services
# in <catalog>.tools, each with a tool allow-list (same tools Microsoft's agents use).
#
#   PROFILE=my-ws CATALOG=prior_auth ./scripts/setup_mcp_services.sh
#
# The UI path does the same thing and is the fallback if your CLI version
# differs: Unity Gateway -> MCPs -> + MCP -> "Connect an existing MCP server"
# (see docs/RUNBOOK.md, step 5B). Check flags with:
#   databricks connections create -h
#   databricks ai-gateway create-mcp-service -h
set -euo pipefail
PROFILE="${PROFILE:-DEFAULT}"
CATALOG="${CATALOG:-prior_auth}"
SCHEMA="${MCP_SCHEMA:-tools}"

# service_name|base_url|allowed tools (comma separated)
SERVERS=(
  "npi_registry|https://hcls.mcp.claude.com/npi_registry/mcp|npi_validate,npi_lookup,npi_search"
  "icd10_codes|https://hcls.mcp.claude.com/icd10_codes/mcp|validate_code,lookup_code,search_codes,get_hierarchy,get_by_category,get_by_body_system"
  "cms_coverage|https://hcls.mcp.claude.com/cms_coverage/mcp|search_national_coverage,search_local_coverage,get_coverage_document,get_contractors,get_whats_new_report,batch_get_ncds,sad_exclusion_list"
  "clinical_trials|https://hcls.mcp.claude.com/clinical_trials/mcp|search_trials,get_trial_details,search_by_eligibility,search_investigators,analyze_endpoints,search_by_sponsor"
  "pubmed|https://pubmed.mcp.claude.com/mcp|search_articles,get_article_metadata,find_related_articles,lookup_article_by_citation"
)

for entry in "${SERVERS[@]}"; do
  IFS="|" read -r NAME URL TOOLS <<< "$entry"
  HOST="$(echo "$URL" | sed -E 's#(https://[^/]+).*#\1#')"
  BASE="$(echo "$URL" | sed -E 's#https://[^/]+##')"
  CONN="pa_mcp_${NAME}"

  echo "== ${NAME}: connection ${CONN} -> ${URL}"
  if ! databricks connections get "${CONN}" --profile "${PROFILE}" >/dev/null 2>&1; then
    # These servers need no credentials; the HTTP connection still requires a
    # token field, so a placeholder is stored.
    databricks connections create --profile "${PROFILE}" --json "{
      \"name\": \"${CONN}\",
      \"connection_type\": \"HTTP\",
      \"comment\": \"Anthropic healthcare MCP server (${NAME}) for prior authorization review\",
      \"options\": {\"host\": \"${HOST}\", \"port\": \"443\", \"base_path\": \"${BASE}\",
                    \"bearer_token\": \"not-required\", \"is_mcp_connection\": \"true\"}
    }"
  fi

  SELECTORS="$(echo "$TOOLS" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip().split(",")))')"
  echo "== ${NAME}: MCP service ${CATALOG}.${SCHEMA}.${NAME}"
  if databricks ai-gateway get-mcp-service "mcp-services/${CATALOG}.${SCHEMA}.${NAME}" --profile "${PROFILE}" >/dev/null 2>&1; then
    echo "   already exists, skipping"
    continue
  fi
  databricks ai-gateway create-mcp-service "schemas/${CATALOG}.${SCHEMA}" "${NAME}" --profile "${PROFILE}" --json "{
    \"comment\": \"Governed ${NAME} MCP for prior authorization agents\",
    \"config\": {
      \"source_connection\": {\"name\": \"connections/${CONN}\"},
      \"include_tool_selectors\": ${SELECTORS},
      \"rate_limits\": [{\"key\": \"RATE_LIMIT_KEY_SERVICE\", \"renewal_period\": \"RATE_LIMIT_RENEWAL_PERIOD_MINUTE\", \"requests\": 600}]
    }
  }"
done

echo
echo "Done. Grant the agent service principal EXECUTE on each service, e.g.:"
echo "  GRANT USE SCHEMA, EXECUTE ON SCHEMA ${CATALOG}.${SCHEMA} TO \`<agent-sp-application-id>\`;"
echo "Then set mcp_mode=service in databricks.yml and re-run the pa_agents_deploy job."
