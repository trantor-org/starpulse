"""The board machine's `tiers`: the state ids the Star Map draws at each stage, beside its `mainLine`."""

import json

import pytest
from pydantic import ValidationError
from starpulse.contracts.api.dto.machine import Machine
from starpulse.contracts.api.schema import SCHEMA

STATES = [
    {"id": "new", "name": "New", "initial": True, "final": False},
    {"id": "ready", "name": "Ready", "initial": False, "final": False},
    {"id": "done", "name": "Done", "initial": False, "final": True},
]


def test_a_machine_carries_its_tiers_in_order_and_none_by_default() -> None:
    tiers = [["new"], ["ready"], ["done"]]

    assert Machine.model_validate({"states": STATES, "transitions": [], "tiers": tiers}).tiers == tiers
    assert Machine.model_validate({"states": STATES, "transitions": []}).tiers is None


def test_a_tier_is_a_list_of_state_ids() -> None:
    with pytest.raises(ValidationError):
        Machine.model_validate({"states": STATES, "transitions": [], "tiers": ["new", "ready"]})


def test_the_checked_in_schema_names_tiers_on_the_machine() -> None:
    machine = json.loads(SCHEMA.read_text())["$defs"]["Machine"]["properties"]

    assert machine["tiers"]["description"]
    assert "mainLine" in machine
