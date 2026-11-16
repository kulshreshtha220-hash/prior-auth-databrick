#!/usr/bin/env bash
# Store the agent endpoints' service principal OAuth secret in a secret scope.
# Create the service principal + OAuth secret first (Settings -> Identity and access
# -> Service principals -> Add; then "Secrets" tab -> Generate secret).
#
#   PROFILE=my-ws SP_CLIENT_ID=... SP_CLIENT_SECRET=... ./scripts/setup_agent_identity.sh
set -euo pipefail
PROFILE="${PROFILE:-DEFAULT}"
SCOPE="${SCOPE:-prior-auth}"
: "${SP_CLIENT_ID:?set SP_CLIENT_ID (application id of the service principal)}"
: "${SP_CLIENT_SECRET:?set SP_CLIENT_SECRET (OAuth secret)}"

databricks secrets create-scope "${SCOPE}" --profile "${PROFILE}" 2>/dev/null || echo "scope ${SCOPE} exists"
databricks secrets put-secret "${SCOPE}" sp_client_id --string-value "${SP_CLIENT_ID}" --profile "${PROFILE}"
databricks secrets put-secret "${SCOPE}" sp_client_secret --string-value "${SP_CLIENT_SECRET}" --profile "${PROFILE}"
echo "Secrets stored in scope ${SCOPE}. Now run the grants in docs/RUNBOOK.md step 3."
