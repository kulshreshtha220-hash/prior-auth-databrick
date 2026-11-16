"""Offline check of databricks.yml + resources/*.yml against the CLI's bundle JSON schema.

Usage: databricks bundle schema > /tmp/schema.json && python scripts/validate_bundle_schema.py /tmp/schema.json
(`databricks bundle validate` needs workspace auth; this does not.)
"""
import glob
import json
import sys

import jsonschema
import yaml

raw = open(sys.argv[1]).read()
schema = json.loads(raw[raw.index("{"):])


def fix(o):  # Python's re has no \p{L}; keep "is an interpolation" semantics
    if isinstance(o, dict):
        return {k: (r"^\$\{[^}]+\}$" if k == "pattern" else fix(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [fix(x) for x in o]
    return o


root = yaml.safe_load(open("databricks.yml"))
for f in sorted(glob.glob("resources/*.yml")):
    for k, v in (yaml.safe_load(open(f)).get("resources") or {}).items():
        root.setdefault("resources", {}).setdefault(k, {}).update(v)
errs = list(jsonschema.Draft7Validator(fix(schema)).iter_errors(root))


def leaf(e):
    if e.context:
        return min((leaf(c) for c in e.context), key=lambda x: len(x[1]))
    return (list(e.absolute_path), e.message[:200])


for e in errs:
    print(leaf(e))
print("schema errors:", len(errs))
sys.exit(1 if errs else 0)
