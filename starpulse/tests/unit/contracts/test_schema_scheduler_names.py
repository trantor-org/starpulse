"""The public schema names the Scheduler, never Autopilot (the page label alone keeps that word)."""

import json
from pathlib import Path

import starpulse

SCHEMA = Path(starpulse.__file__).parent / "schemas" / "api.schema.json"


def _defs() -> set[str]:
    document = json.loads(SCHEMA.read_text())
    return set(document.get("$defs", document.get("definitions", {})))


def test_schema_names_scheduler_status() -> None:
    assert "SchedulerStatus" in _defs()


def test_schema_has_no_autopilot_body() -> None:
    assert [name for name in _defs() if name.lower().startswith("autopilot")] == []
