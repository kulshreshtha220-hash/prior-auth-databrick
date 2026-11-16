# Runbook: deploy Prior Authorization Review on Databricks

Follow the steps in order. Each step says **who** (DE 1, DE 2 or a workspace admin), **where**
(UI, SQL editor, terminal) and **how to check** it worked. Expected total for a first deployment:
about one day, most of it waiting for the agent endpoints to build.

Replace these placeholders everywhere: `<profile>` (CLI profile), `<warehouse-id>`,
`<agent-sp-app-id>` (agent service principal), `<app-sp-app-id>` (app service principal).

---

## Step 0. Prerequisites (admin, 30 min)

- [ ] Workspace with Unity Catalog, serverless compute, **Databricks Apps**, **Model Serving**,
      **Lakebase** and **Unity Gateway** enabled.
- [ ] A serverless or pro **SQL warehouse**. Copy its id (SQL Warehouses → warehouse → Connection details).
- [ ] Permission to create a catalog (or an existing catalog you own).
- [ ] Databricks CLI ≥ 0.270 on the machine you deploy from (or use the workspace **Web Terminal**):
      `databricks auth login --host https://<workspace-url> --profile <profile>`
- [ ] Serverless egress allows `hcls.mcp.claude.com`, `pubmed.mcp.claude.com`, `ftp.cdc.gov`,
      `downloads.cms.gov`, `npiregistry.cms.hhs.gov` (Settings → Network policies, if your workspace
      restricts egress).
- [ ] Compliance sign-off: only codes, NPIs and search terms go to the external MCP servers, but the
      Delta and Lakebase tables hold PHI. Use synthetic or de-identified cases until approved.

**Check:** `databricks current-user me --profile <profile>` prints your user.

---

## Step 1. Put the code in a Databricks Git folder (DE 1, 20 min)

A Git folder is a Databricks workspace folder linked to a remote Git repo. Everyone with access sees
the same code and can work on branches.

1. Create an empty repo in your company Git (GitHub, Azure DevOps, GitLab or Bitbucket), for example
   `prior-auth-databricks`.
2. Unzip the delivered `prior-auth-databricks.zip`, then push it:
   ```bash
   cd prior-auth-databricks
   git init -b main && git add . && git commit -m "Prior auth review on Databricks: initial import"
   git remote add origin <repo-url> && git push -u origin main
   ```
3. In Databricks: **Settings → Linked accounts** → connect your Git provider (each DE does this once).
4. **Workspace → Users → <you> → Create → Git folder** → paste the repo URL → Create.
   Each DE makes their **own** Git folder and works on a branch (`de1/agents`, `de2/app`).
5. For a shared, read-only copy for reviewers/leads: create one Git folder under
   `/Workspace/Shared/prior-auth` on `main`, then **Share** it with the team group (Can Read). Only CI
   or a lead pulls this one.

**Check:** the Git folder shows `databricks.yml`, `src/`, `docs/`.

> Who can see what: Git folders follow workspace folder permissions. Your personal Git folder is
> private unless you share it. Code changes reach others only through Git (commit → push → they pull).

---

## Step 2. Create the catalog, schemas and volumes (DE 2, 10 min)

Open **SQL Editor**, pick the warehouse, run:

```sql
CREATE CATALOG IF NOT EXISTS prior_auth;
CREATE SCHEMA  IF NOT EXISTS prior_auth.core  COMMENT 'Prior authorization review data';
CREATE SCHEMA  IF NOT EXISTS prior_auth.tools COMMENT 'Unity Gateway MCP services';
CREATE VOLUME  IF NOT EXISTS prior_auth.core.raw_documents;
CREATE VOLUME  IF NOT EXISTS prior_auth.core.generated_reports;
```

If you must use another catalog or schema name, change `catalog` / `schema` in `databricks.yml`
**and** `PA_CATALOG` / `PA_SCHEMA` in `src/app/app.yaml`.

**Check:** Catalog Explorer shows `prior_auth.core` with two volumes.

---

## Step 3. Identity for the agent endpoints (admin + DE 1, 20 min)

The four agent endpoints call the model, the MCP services and the SQL warehouse as a **service
principal** (works for every model type and MCP services).

1. **Settings → Identity and access → Service principals → Add** → name `pa-agents`.
   Open it → **Secrets → Generate secret**. Copy the client id (application id) and secret.
2. Store them in a secret scope:
   ```bash
   PROFILE=<profile> SP_CLIENT_ID=<agent-sp-app-id> SP_CLIENT_SECRET=<secret> ./scripts/setup_agent_identity.sh
   ```
3. Grants (SQL editor):
   ```sql
   GRANT USE CATALOG ON CATALOG prior_auth TO `<agent-sp-app-id>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA prior_auth.core TO `<agent-sp-app-id>`;   -- prompts + reference tables
   GRANT EXECUTE ON SCHEMA prior_auth.core TO `<agent-sp-app-id>`;              -- Prompt Registry reads
   GRANT USE SCHEMA, EXECUTE ON SCHEMA prior_auth.tools TO `<agent-sp-app-id>`; -- MCP services (step 5B)
   ```
4. Model access: give the SP `EXECUTE` on the model it will use, e.g. in Catalog Explorer
   `system → ai → <model> → Permissions`, or `CAN_QUERY` on the `databricks-<model>` serving endpoint.
5. SQL warehouse → **Permissions** → add `pa-agents` with **Can use**.

**Check:** `databricks secrets list-secrets prior-auth --profile <profile>` lists `sp_client_id`, `sp_client_secret`.

---

## Step 4. Create the Lakebase database (DE 2, 10 min)

1. **Compute → Lakebase Postgres → Create** (project / instance name `pa-lakebase`, smallest capacity,
   default database `databricks_postgres`).
2. Wait until it is **Available**.

The app creates its tables (`pa.cases`, `pa.decisions`, `pa.audit_events`) and the LangGraph
checkpoint tables on first start; no SQL needed.

---

## Step 5. MCP servers (DE 1)

**5A. Start with `direct` mode (default for `dev`).** The agents call the public MCP URLs
directly from Model Serving. Nothing to set up beyond the egress rule in step 0.

**5B. Switch to governed MCP services (required for `prod`, 30 min).** Registers each server in
Unity Gateway with a tool allow-list and rate limit:

```bash
PROFILE=<profile> CATALOG=prior_auth ./scripts/setup_mcp_services.sh
```

If your CLI rejects a flag, do it in the UI for each of the 5 servers: **Unity Gateway → MCPs →
+ MCP → Connect an existing MCP server** → catalog `prior_auth`, schema `tools`, name exactly
`npi_registry` / `icd10_codes` / `cms_coverage` / `clinical_trials` / `pubmed` → new connection with
the URL from the table below (no authentication / bearer `not-required`) → **Create & load tools** →
select the tools → **Create MCP Service**.

| Name | URL |
|---|---|
| `npi_registry` | `https://hcls.mcp.claude.com/npi_registry/mcp` |
| `icd10_codes` | `https://hcls.mcp.claude.com/icd10_codes/mcp` |
| `cms_coverage` | `https://hcls.mcp.claude.com/cms_coverage/mcp` |
| `clinical_trials` | `https://hcls.mcp.claude.com/clinical_trials/mcp` |
| `pubmed` | `https://pubmed.mcp.claude.com/mcp` |

Then set `mcp_mode: service` (already the `prod` default) and redeploy agents (step 9).

**Check:** Unity Gateway → MCPs lists the 5 services with their tools.

---

## Step 6. Deploy the bundle (DE 2, 15 min)

From a terminal in the repo (laptop or Web Terminal):

```bash
databricks bundle validate -t dev --var warehouse_id=<warehouse-id> -p <profile>
databricks bundle deploy   -t dev --var warehouse_id=<warehouse-id> -p <profile>
```

To avoid typing variables every time, create `.databricks/bundle/dev/variable-overrides.json`
(not committed):

```json
{ "warehouse_id": "<warehouse-id>", "app_name": "pa-review-<yourname>" }
```

This creates the **app** `pa-review-<you>` (not started yet) and **4 jobs**: `pa_setup`,
`pa_agents_deploy`, `pa_reference_refresh`, `pa_batch_evaluation`.

If your workspace shows bundle deployment in the Git folder UI (open `databricks.yml` → Deployments),
you can deploy from there instead; otherwise use the Web Terminal, which has the CLI built in.

**Check:** Jobs & Pipelines shows four jobs prefixed `[dev ...]`; Compute → Apps shows the app.

---

## Step 7. Attach Lakebase to the app and note its service principal (DE 2, 10 min)

1. **Compute → Apps → pa-review-<you> → Edit → Resources → + Add resource → Database** →
   select `pa-lakebase`, database `databricks_postgres`, permission **Can connect and create** →
   resource key `database` → Save.
2. On the app page, **Authorization** tab: copy the app's **service principal application id**
   (`<app-sp-app-id>`).
3. Put it in `variable-overrides.json` as `"app_sp": "<app-sp-app-id>"` and run
   `databricks bundle deploy -t dev` again.

---

## Step 8. Run setup: tables, seeds, grants, prompts (DE 2, 10 min)

```bash
databricks bundle run pa_setup -t dev -p <profile>
```

Creates the 14 Delta tables, seeds curated CPT codes and 4 evaluation cases, grants the app SP
access, and registers the 4 SKILL.md prompts as `prior_auth.core.<agent>_skill@prod`.

**Check:** `SHOW TABLES IN prior_auth.core` returns 14 tables; the `register_prompts` task output
shows 4 prompts registered with `@prod` (also visible in the MLflow **Prompts** page).

---

## Step 9. Deploy the four agents (DE 1, 30–60 min, mostly waiting)

```bash
databricks bundle run pa_agents_deploy -t dev -p <profile>
```

What it does: `pick_model` lists the models in your workspace and picks the best available one
(Claude Sonnet first; see the notebook output for the list) → `register_prompts` → 4 parallel
`deploy_*` tasks (log `agent.py` to UC as `prior_auth.core.pa_<agent>_agent`, then
`agents.deploy` to endpoints `pa-<agent>-agent`, grant the app CAN_QUERY) → `smoke_test` (runs the
sample case through all four endpoints and the gates).

To force a model, set `llm_model` in `databricks.yml` (e.g. `system.ai.claude-sonnet-4-5` or
`databricks-claude-sonnet-4-5`).

**Check:** Serving → 4 endpoints `pa-compliance-agent` … `pa-synthesis-agent` are **Ready**, and the
`smoke_test` output prints `Gates: approve approved 0.9x HIGH` (exact numbers vary by model).

---

## Step 10. Start the app and run the sample case (DE 2, 10 min)

```bash
databricks bundle run pa_review_app -t dev -p <profile>
```

Open the app URL → **Load Sample Case** → **Submit for Review**. You should see the progress
tracker move through Pre-flight → Phase 1 → 2 → 3 → 4 in 1–4 minutes, then the recommendation,
the four agent tabs, the audit trail and the PDF download. Click **Accept Recommendation** or
**Override** to generate the letter.

Give reviewers access: app page → **Permissions** → add the reviewers group with **Can use**.

**Check (SQL editor):**
```sql
SELECT * FROM prior_auth.core.gate_results ORDER BY created_at DESC LIMIT 10;
SELECT agent, model, prompt_version, status, duration_s FROM prior_auth.core.agent_runs ORDER BY created_at DESC LIMIT 8;
LIST '/Volumes/prior_auth/core/generated_reports/';
```

---

## Step 11. Reference data and evaluation jobs (DE 1, 30 min)

```bash
databricks bundle run pa_reference_refresh -t dev -p <profile>   # ICD-10-CM, NCD/LCD, NPI cache
databricks bundle run pa_batch_evaluation  -t dev -p <profile>   # MLflow 3 evaluation on eval_cases
```

Then un-pause both schedules (job page → Schedule → Unpause): reference refresh weekly (Sun 03:00
UTC), evaluation nightly (02:30 UTC). Check the CDC/CMS file URLs in `05_reference_refresh` every
October when the code sets change.

**Check:** `SELECT count(*) FROM prior_auth.core.ref_icd10cm` returns tens of thousands of rows;
the evaluation run in MLflow (Experiments → `prior-auth-evaluation`) shows accuracy and per-case scores.

---

## Step 12. Production

1. Merge to `main`; deploy from the shared Git folder or CI with `-t prod`
   (`app_name: pa-review`, `mcp_mode: service`, workspace root under `/Workspace/Shared/.bundle`).
2. Repeat steps 7–11 for the `prod` target (a separate app and endpoints).
3. Turn on budgets and rate limits in Unity Gateway; review who has `EXECUTE` on the model and MCP services.
4. Move `@prod` on a prompt only after `pa_batch_evaluation` passes.

---

## Where to look when something breaks

| Symptom | Where to look | Usual fix |
|---|---|---|
| App shows "Lakebase not attached" in logs | App → Logs | Step 7.1: add the `database` resource, restart the app |
| Review stuck at Phase 1, agent `error` | Serving → endpoint → Logs; MLflow trace | Endpoint not Ready, SP lacks model `EXECUTE`, or secret scope wrong (step 3) |
| Every check says UNKNOWN | `agent_runs.unavailable_sources` | Egress blocked (step 0) or MCP services missing / no `EXECUTE` (step 5B) |
| `403 ... pay-per-token ... use Unity Gateway` | Endpoint logs | Use `system.ai.<model>` for `llm_model`, grant SP `EXECUTE` on it |
| `ai_parse_document` fails on upload | App logs | Warehouse must be serverless/pro and in a supported region |
| Delta tables empty but app works | App logs "Delta write failed" | App SP needs `MODIFY` on `prior_auth.core` (rerun `pa_setup` with `app_sp`) |
| Bundle deploy: app name invalid | — | Max 30 chars, lowercase letters, digits, hyphens; set `app_name` |

## Updating rules without a redeploy

Edit `src/app/pa_core/skills/<skill>/SKILL.md` in your Git folder → commit → run notebook
`02_register_prompts` (or the `pa_setup` job). Agents pick up the new `@prod` version on their next
cold start; to apply immediately, rerun `pa_agents_deploy` (no code change needed).

## What was tested before handover, and what was not

Tested (outside Databricks): 33 automated tests covering the gate rules against the SKILL.md worked
examples, UNKNOWN handling, the agent tool loop, the ResponsesAgent wrapper, the full API flow
(review → stored → decision → letter), and the Lakebase store + LangGraph checkpoints against a real
Postgres 16; logging and reloading the agent with MLflow (`pa_core` and SKILL.md travel with the
model); the React UI end to end in mock mode; the bundle against the CLI's JSON schema.

Not yet tested (needs your workspace): live model calls, live MCP calls, Model Serving deployment,
Lakebase connection, `ai_parse_document`, the reference-data downloads and the evaluation job.
Steps 9–11 are where these get proven; expect small fixes there.
