# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Log, register and deploy one agent to Model Serving
# MAGIC Run once per agent (`agent` widget). The `pa_agents_deploy` job runs the four in parallel.
# MAGIC
# MAGIC * Logs `src/agents/agent.py` (MLflow ResponsesAgent) with `pa_core` as code dependency
# MAGIC * Registers `<catalog>.<schema>.pa_<agent>_agent` in Unity Catalog and sets alias `champion`
# MAGIC * Deploys / updates endpoint `<prefix>-<agent>-agent` with `databricks.agents.deploy`
# MAGIC   (tracing, inference tables and the review app come with it)
# MAGIC
# MAGIC **Auth inside the endpoint** (`auth_mode`):
# MAGIC * `service_principal` (default): the endpoint authenticates as a service principal whose
# MAGIC   OAuth secret is in a secret scope. Works for Unity Gateway models, MCP services and SQL.
# MAGIC * `passthrough`: automatic credentials from the logged `resources` (serving-endpoint models
# MAGIC   and SQL warehouse only).

# COMMAND ----------

# MAGIC %pip install -q "mlflow[databricks]>=3.4" databricks-agents "databricks-sdk>=0.60" "openai>=1.60" "mcp>=1.24,<2" databricks-mcp "pydantic>=2.7"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.dropdown("agent", "compliance", ["compliance", "clinical", "coverage", "synthesis"])
dbutils.widgets.text("catalog", "prior_auth")
dbutils.widgets.text("schema", "core")
dbutils.widgets.text("llm_model", "auto", "LLM: auto (from pick_model task) | system.ai.<model> | databricks-<model>")
dbutils.widgets.dropdown("mcp_mode", "service", ["service", "direct", "off"])
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("endpoint_prefix", "pa")
dbutils.widgets.dropdown("auth_mode", "service_principal", ["service_principal", "passthrough"])
dbutils.widgets.text("secret_scope", "prior-auth")
dbutils.widgets.dropdown("scale_to_zero", "true", ["true", "false"])
dbutils.widgets.text("app_sp", "", "App service principal application id (gets CAN_QUERY)")

agent = dbutils.widgets.get("agent")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
llm_model = dbutils.widgets.get("llm_model").strip()
mcp_mode = dbutils.widgets.get("mcp_mode")
warehouse_id = dbutils.widgets.get("warehouse_id").strip()
endpoint_name = f"{dbutils.widgets.get('endpoint_prefix')}-{agent}-agent"
auth_mode, scope = dbutils.widgets.get("auth_mode"), dbutils.widgets.get("secret_scope")
model_name = f"{catalog}.{schema}.pa_{agent}_agent"

# llm_model=auto -> use the model chosen by the pick_model task (00_pick_model).
if llm_model == "auto":
    llm_model = dbutils.jobs.taskValues.get(taskKey="pick_model", key="llm_model", debugValue="")
    if not llm_model:
        raise ValueError("llm_model=auto needs the pick_model task (run the job) or set llm_model explicitly")
print(f"agent={agent} model={model_name} endpoint={endpoint_name} llm={llm_model} mcp={mcp_mode} auth={auth_mode}")

# COMMAND ----------

import os, json
import mlflow
from mlflow.models.resources import DatabricksServingEndpoint, DatabricksSQLWarehouse

mlflow.set_registry_uri("databricks-uc")
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/prior-auth-agents")

agent_file = os.path.abspath("../agents/agent.py")
pa_core_dir = os.path.abspath("../app/pa_core")
# MLflow imports agent.py while logging, so pa_core must be importable here too.
import sys
sys.path.insert(0, os.path.dirname(pa_core_dir))

model_config = {
    "agent_key": agent,
    "env": {
        "PA_CATALOG": catalog, "PA_SCHEMA": schema, "PA_LLM_MODEL": llm_model, "PA_MCP_MODE": mcp_mode,
        "PA_PROMPT_ALIAS": "prod", "PA_USE_PROMPT_REGISTRY": "true", "PA_REFERENCE_FALLBACK": "true",
        "DATABRICKS_WAREHOUSE_ID": warehouse_id, "MLFLOW_DISABLE_AGENT_HINT": "1",
    },
}
resources = []
if not llm_model.count(".") >= 2:
    resources.append(DatabricksServingEndpoint(endpoint_name=llm_model))
if warehouse_id:
    resources.append(DatabricksSQLWarehouse(warehouse_id=warehouse_id))

example = {"input": [{"role": "user", "content": json.dumps({"patient_name": "Test", "diagnosis_codes": ["R91.1"], "procedure_codes": ["31628"], "provider_npi": "1720180003", "clinical_notes": "test"})}]}

with mlflow.start_run(run_name=f"log_{agent}"):
    info = mlflow.pyfunc.log_model(
        name="agent",
        python_model=agent_file,
        model_config=model_config,
        code_paths=[pa_core_dir],
        resources=resources or None,
        input_example=example,
        pip_requirements=[
            "mlflow[databricks]>=3.4", "databricks-sdk>=0.60", "openai>=1.60", "pydantic>=2.7",
            "mcp>=1.24,<2", "databricks-mcp", "httpx>=0.27",
        ],
        registered_model_name=model_name,
    )
version = info.registered_model_version
mlflow.MlflowClient(registry_uri="databricks-uc").set_registered_model_alias(model_name, "champion", version)
print(f"Registered {model_name} v{version}")

# COMMAND ----------

from databricks import agents

env_vars = {}
if auth_mode == "service_principal":
    host = spark.conf.get("spark.databricks.workspaceUrl")
    env_vars = {
        "DATABRICKS_HOST": f"https://{host}",
        "DATABRICKS_CLIENT_ID": f"{{{{secrets/{scope}/sp_client_id}}}}",
        "DATABRICKS_CLIENT_SECRET": f"{{{{secrets/{scope}/sp_client_secret}}}}",
    }

deployment = agents.deploy(
    model_name, version,
    endpoint_name=endpoint_name,
    scale_to_zero=dbutils.widgets.get("scale_to_zero") == "true",
    environment_vars=env_vars or None,
    tags={"project": "prior-auth", "agent": agent},
)
print("Endpoint:", deployment.endpoint_name)
dbutils.jobs.taskValues.set(key="endpoint", value=deployment.endpoint_name)

# COMMAND ----------

# Let the app's service principal call this endpoint.
app_sp = dbutils.widgets.get("app_sp").strip()
if app_sp:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel

    w = WorkspaceClient()
    ep = w.serving_endpoints.get(endpoint_name)
    w.serving_endpoints.update_permissions(ep.id, access_control_list=[
        ServingEndpointAccessControlRequest(service_principal_name=app_sp,
                                            permission_level=ServingEndpointPermissionLevel.CAN_QUERY)])
    print(f"Granted CAN_QUERY on {endpoint_name} to {app_sp}")
