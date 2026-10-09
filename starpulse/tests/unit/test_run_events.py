"""The runs stream contract: its entry shape."""

from __future__ import annotations

from starpulse._internal.runs import run_events


def test_an_entry_omits_the_step_and_depends_of_a_run_level_event() -> None:
    assert run_events.entry("end", "w", "r", "failed", now=5.0) == {
        "time": 5.0,
        "phase": "end",
        "workflow": "w",
        "run_id": "r",
        "status": "failed",
    }


def test_a_step_entry_names_the_step_and_the_steps_it_waits_on() -> None:
    assert run_events.entry("start", "w", "r", "running", now=5.0, step="load", depends=["fetch"]) == {
        "time": 5.0,
        "phase": "start",
        "workflow": "w",
        "run_id": "r",
        "status": "running",
        "step": "load",
        "depends": ["fetch"],
    }


def test_an_entry_from_an_instance_names_it() -> None:
    assert run_events.entry("start", "w", "r", "running", now=5.0, instance="cron")["instance"] == "cron"
