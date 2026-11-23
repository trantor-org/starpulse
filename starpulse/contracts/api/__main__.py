"""Regenerate `api.schema.json` and `openapi.json`: `python -m starpulse.contracts.api`."""

from starpulse.contracts.api.openapi import OPENAPI, render
from starpulse.contracts.api.schema import SCHEMA, schema

SCHEMA.write_text(schema())
OPENAPI.write_text(render())
