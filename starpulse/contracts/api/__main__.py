"""Regenerate `api.schema.json`: `python -m starpulse.contracts.api`."""

from starpulse.contracts.api.schema import SCHEMA, schema

SCHEMA.write_text(schema())
