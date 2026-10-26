"""`starpulse.sessions`: the public Activity classification and Health folds are those StarPulse stores and serves."""

import json
import re
from typing import Any

import pytest

from starpulse import sessions
from starpulse._internal.analytics import Analytics, Labeller
from starpulse.runtime.config import Config
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.api.dto.health import SessionHealth, SliceHealth
from starpulse.flow_metrics import session_health as fold
from starpulse.harness_telemetry import activity, telemetry
from starpulse.tests.unit.harness_telemetry.test_telemetry import FIXTURES

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:[\w.-]+/)*task-(\d+)"),
    key_format="TASK-{}",
)


def _exports(*names: str) -> list[dict[str, Any]]:
    return [json.loads(line) for name in names for line in (FIXTURES / name).read_text().splitlines()]


BOTH = _exports("claude_code/otlp.ndjson", "codex/otlp.ndjson")


def test_activities_is_the_classification_stored_signals_carry() -> None:
    assert sessions.activities is activity.activities
    assert (
        sessions.SHELLS,
        sessions.SHELL_READ,
        sessions.SHELL_SEARCH,
        sessions.SHELL_OTHER,
        sessions.TOOL_OTHER,
    ) == (
        activity.SHELLS,
        activity.SHELL_READ,
        activity.SHELL_SEARCH,
        activity.SHELL_OTHER,
        activity.TOOL_OTHER,
    )


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        (
            "Bash",
            {"command": "cd repo && uv run make test | tail -5; git push origin HEAD"},
            ["make test", "git push"],
        ),
        (
            "Bash",
            {"command": "cat README.md; rg -n foo"},
            ["shell_read", "shell_search"],
        ),
        ("mcp__github__create_pull_request", {}, ["create_pull_request"]),
        ("ls | wc -l", {}, ["tool_other"]),
    ],
)
def test_activities_lifts_a_tool_call_to_labels_with_no_arguments(
    tool: str, tool_input: dict[str, str], expected: list[str]
) -> None:
    assert sessions.activities(tool, tool_input) == expected


def test_session_health_is_the_internal_fold_of_the_exports_signals_as_dtos() -> None:
    rows = sessions.session_health(BOTH, KEYS)

    found = telemetry.held(s for payload in BOTH for s in telemetry.signals(payload, keys=KEYS))
    assert all(type(row) is SessionHealth for row in rows)
    assert [row.model_dump() for row in rows] == fold.session_health(found, KEYS)
    assert {(row.harness, row.task) for row in rows} == {
        ("claude-code", "TASK-1"),
        ("codex", None),
    }


def test_a_record_two_exports_both_carry_counts_once() -> None:
    assert sessions.session_health(BOTH + BOTH, KEYS) == sessions.session_health(BOTH, KEYS)


def test_without_keys_no_row_names_a_task() -> None:
    assert {row.task for row in sessions.session_health(BOTH)} == {None}


def test_the_config_analytics_table_is_read_and_its_labeller_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: object) -> str:
        raise AssertionError("session_health called the labeller")

    monkeypatch.setattr(telemetry, "intent_label", refuse)
    labelled = Analytics(
        injected_openings=("<",),
        labeller=Labeller(url="http://labeller.invalid", model="m", criteria={"a": "b"}),
    )
    config = Config(None, "ic", (), analytics=labelled)

    rows = sessions.session_health(_exports("claude_code/otlp.ndjson"), KEYS, config)

    assert rows == sessions.session_health(
        _exports("claude_code/otlp.ndjson"),
        KEYS,
        Config(None, "ic", (), analytics=Analytics(injected_openings=("<",))),
    )
    assert all(row.prompt_labels == {} for row in rows)


def test_slice_health_folds_the_dtos_as_the_route_folds_its_rows() -> None:
    rows = sessions.session_health(BOTH, KEYS)

    slices = sessions.slice_health(rows)

    assert all(type(s) is SliceHealth for s in slices)
    assert [s.model_dump() for s in slices] == fold.slice_health(row.model_dump() for row in rows)
    assert [(s.task, s.sessions) for s in slices] == [("TASK-1", 1)]
