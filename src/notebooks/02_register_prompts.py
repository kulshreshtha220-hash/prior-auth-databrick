# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Register agent rules (SKILL.md) in the MLflow Prompt Registry
# MAGIC Each agent's SKILL.md (from the Microsoft accelerator) becomes a versioned prompt in Unity
# MAGIC Catalog: `<catalog>.<schema>.<agent>_skill`. The `prod` alias is what the agents load.
# MAGIC Clinical SMEs change rules by registering a new version and moving the alias, with no redeploy.
# MAGIC A new version is only created when the text changed.

# COMMAND ----------

# MAGIC %pip install -q "mlflow[databricks]>=3.4"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "prior_auth")
dbutils.widgets.text("schema", "core")
dbutils.widgets.text("alias", "prod")
dbutils.widgets.dropdown("move_alias", "true", ["true", "false"], "Point alias at the new version")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
alias, move_alias = dbutils.widgets.get("alias"), dbutils.widgets.get("move_alias") == "true"

# COMMAND ----------

import os
import mlflow

mlflow.set_registry_uri("databricks-uc")
skills_root = os.path.abspath("../app/pa_core/skills")
SKILLS = {"compliance": "compliance-review", "clinical": "clinical-review",
          "coverage": "coverage-assessment", "synthesis": "synthesis-decision"}

def strip_front_matter(t: str) -> str:
    if t.startswith("---"):
        end = t.find("\n---", 3)
        if end != -1:
            return t[end + 4:].lstrip()
    return t

for agent, folder in SKILLS.items():
    name = f"{catalog}.{schema}.{agent}_skill"
    text = strip_front_matter(open(os.path.join(skills_root, folder, "SKILL.md"), encoding="utf-8").read())
    current = None
    try:
        current = mlflow.genai.load_prompt(f"prompts:/{name}@{alias}")
    except Exception:
        pass
    if current is not None and current.template == text:
        print(f"{name}: unchanged (v{current.version} @{alias})")
        continue
    p = mlflow.genai.register_prompt(
        name=name, template=text,
        commit_message=f"SKILL.md {folder} from repo",
        tags={"agent": agent, "source": "microsoft-pa-accelerator", "folder": folder},
    )
    if move_alias:
        mlflow.genai.set_prompt_alias(name=name, alias=alias, version=p.version)
    print(f"{name}: registered v{p.version}{' and set @' + alias if move_alias else ''}")
