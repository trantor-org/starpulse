"""The create, start and miss request DTOs declare the keys the write handlers parse, and the generated schema carries them."""

from __future__ import annotations

import json
from pathlib import Path

from starpulse.contracts.api.dto.requests import CreateRequest, MissRequest, StartRequest

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "api.schema.json"


def _schema_defs() -> dict:
    return json.loads(SCHEMA.read_text())["$defs"]


def test_create_request_declares_the_keys_the_handler_parses() -> None:
    fields = CreateRequest.model_fields
    assert "task" in fields
    assert "title" in fields
    assert "size" in fields
    assert "skill" in fields
    assert "actor" in fields
    assert "session" in fields
    assert "harness" in fields


def test_start_request_declares_the_keys_the_handler_parses() -> None:
    fields = StartRequest.model_fields
    assert "task" in fields
    assert "profile" in fields
    assert "harness" in fields
    assert "actor" in fields
    assert "session" in fields


def test_miss_request_declares_the_keys_the_handler_parses() -> None:
    fields = MissRequest.model_fields
    assert "task" in fields
    assert "reason" in fields
    assert "actor" in fields
    assert "session" in fields
    assert "harness" in fields


def test_api_schema_carries_the_create_start_and_miss_bodies() -> None:
    defs = _schema_defs()
    for name in ("CreateRequest", "StartRequest", "MissRequest"):
        assert name in defs, f"api.schema.json is missing the {name} definition"
    create_props = defs["CreateRequest"]["properties"]
    assert "title" in create_props
    assert "size" in create_props
    assert "skill" in create_props
    start_props = defs["StartRequest"]["properties"]
    assert "profile" in start_props
    miss_props = defs["MissRequest"]["properties"]
    assert "reason" in miss_props
