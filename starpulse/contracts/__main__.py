"""Regenerate the JSON Schema files under `schemas/`: `python -m starpulse.contracts`."""

import json

from starpulse.contracts.adapters import SCHEMA_DIR, SCHEMAS

SCHEMA_DIR.mkdir(exist_ok=True)
for schema_name, schema in SCHEMAS.items():
    (SCHEMA_DIR / f"{schema_name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
