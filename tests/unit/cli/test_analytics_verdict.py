"""`starpulse analytics verdict`: win, lose or continue for one named trial cell, read from the scored window."""

import json
from collections.abc import Sequence
from typing import Any

import pytest
from starpulse import github
from starpulse.cli import agent_cli as cli
from starpulse.cli import agent_wire


def _slice(task: str, effort: str, prompts: int) -> dict[str, Any]:
    return {
        "task": task,
        "complete": True,
        "clean": True,
        "operator_prompts": prompts,
        "raises": 0,
        "lowers": 0,
        "harnesses": ["claude-code"],
        "models": ["sonnet"],
        "efforts": [effort],
    }


@pytest.fixture
def scored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A window with eight `sonnet-medium` tasks of one cell, and trials: `sonnet-low` as good, `sonnet-minimal` worse."""
    slices = [_slice(f"TASK-{n}", "medium", n % 2) for n in range(8)]
    slices += [_slice(f"TASK-{10 + n}", "low", n % 2) for n in range(6)]
    slices += [_slice(f"TASK-{20 + n}", "minimal", 8 + n % 2) for n in range(6)]
    window = {"now": 1.0, "window_s": 3600.0, "slices": slices}
    settled = {s["task"]: {"labels": ["kind-execute", "size-3"]} for s in slices}
    monkeypatch.setattr(cli, "_window_read", lambda args, environ, route, keys, params=None: window)
    monkeypatch.setattr(agent_wire, "get_snapshot", lambda base: {"settled": settled})
    monkeypatch.setattr(github, "connect", lambda token: lambda method, path, body: (200, {"items": []}))


def _verdict(capsys: pytest.CaptureFixture[str], profile: str, kind: str = "execute") -> tuple[int, Any]:
    argv: Sequence[str] = ["analytics", "verdict", "--kind", kind, "--size", "3", "--profile", profile, "--repo", "o/r"]
    code = cli.main(argv, {})
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.usefixtures("scored")
def test_a_trial_as_good_as_the_baseline_is_a_win(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _verdict(capsys, "sonnet-low")
    assert code == 0
    assert (doc["kind"], doc["size"], doc["profile"], doc["baseline"]) == ("execute", 3, "sonnet-low", "sonnet-medium")
    assert doc["verdict"] == "win"


@pytest.mark.usefixtures("scored")
def test_a_trial_worse_than_the_baseline_is_a_lose(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _verdict(capsys, "sonnet-minimal")
    assert code == 0
    assert doc["verdict"] == "lose"


@pytest.mark.usefixtures("scored")
def test_a_cell_with_no_trial_is_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    code, doc = _verdict(capsys, "sonnet-high")
    assert code == 4
    assert doc["code"] == "not_found"


def test_an_analytics_read_waits_past_the_default_read_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    waited: list[float] = []

    def get(base: str, path: str, timeout: float = 10.0) -> tuple[int, Any]:
        waited.append(timeout)
        return 200, {"now": 1.0, "window_s": 60.0, "cells": []}

    monkeypatch.setattr(agent_wire, "get", get)
    assert cli.main(["analytics", "cells"], {}) == 0
    capsys.readouterr()
    assert waited[0] > 10.0
