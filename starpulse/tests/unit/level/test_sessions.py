"""Session health and slice health: folds of harness telemetry signals, worked out by hand on recorded exports."""

import json
import re
from datetime import datetime

import pytest

from starpulse._internal.harnesses.telemetry import CLAUDE_CODE, CODEX, Signal, signals
from starpulse._internal.level.sessions import IDLE_S, session_health, slice_health
from starpulse.contracts.adapters import TaskKeys
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES, recorded

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
T0 = datetime.fromisoformat("2026-10-09T10:00:00+00:00").timestamp()
_N = iter(range(10**6))


def sig(kind: str, at: float, *, session: str = "s", harness: str = CLAUDE_CODE, **fields: object) -> Signal:
    """A signal `at` seconds after T0; `fields` set any other `Signal` field."""
    return Signal(harness, session, kind, T0 + at, f"{harness}:{session}:{next(_N)}", **fields)  # type: ignore[arg-type]


def only(rows: list[dict]) -> dict:
    assert len(rows) == 1
    return rows[0]


def test_a_recorded_claude_code_session_is_one_row_for_the_task_its_branch_names() -> None:
    row = only(session_health(recorded("claude_code/otlp.ndjson"), KEYS))

    assert (row["harness"], row["task"], row["kind"]) == (CLAUDE_CODE, "TASK-1", "headless")
    assert (row["prompts"], row["operator_prompts"], row["requests"], row["side_requests"]) == (1, 0, 3, 0)
    assert (row["tool_calls"], row["tool_failures"], row["tools"]) == (2, 2, {"Bash": 2})
    assert row["tokens"] == {"input": 6, "output": 311, "cache_read": 67162, "cache_write": 33895, "reasoning": 0}
    assert row["cost_usd"] == pytest.approx(0.1454182)
    assert (row["models"], row["efforts"], row["model_changes"], row["effort_changes"]) == (
        ["claude-sonnet-5-5"],
        ["medium"],
        0,
        0,
    )
    assert row["rejections"] == {} and row["compactions"] == {} and row["skills"] == {}
    assert row["agent_s"] == pytest.approx(59.956)
    assert (row["operator_wait_s"], row["idle_s"]) == (0, 0)


def test_a_recorded_codex_session_has_no_task_and_its_effort_is_known_from_its_second_request() -> None:
    row = only(session_health(recorded("codex/otlp.ndjson"), KEYS))

    assert (row["harness"], row["task"], row["kind"]) == (CODEX, None, "headless")
    assert (row["requests"], row["tool_calls"], row["tools"]) == (3, 2, {"exec_command": 1, "exec": 1})
    assert row["tokens"] == {
        "input": 12275 + 2264 + 325,
        "output": 70,
        "cache_read": 26112,
        "cache_write": 0,
        "reasoning": 22,
    }
    assert (row["cost_usd"], row["models"], row["efforts"], row["effort_changes"]) == (
        None,
        ["gpt-6-astra"],
        ["medium"],
        0,
    )
    assert row["agent_s"] == pytest.approx(32.905)


def test_the_recorded_older_export_counts_its_skill_and_its_two_turns() -> None:
    found: list[Signal] = []
    for line in (FIXTURES / "claude_code" / "export.ndjson").read_text().splitlines():
        found += signals(json.loads(line))

    row = only(session_health(found, KEYS))

    assert (row["prompts"], row["operator_prompts"], row["skills"]) == (2, 1, {"hello": 1})


def test_a_git_switch_to_a_task_branch_retargets_the_rows_that_follow_it() -> None:
    found = [
        sig("prompt", 0, branch="main"),
        sig("request", 5, branch="main", model="m"),
        sig("branch", 6, branch="main", name="claude/task-7-x"),
        sig("request", 10, branch="main", model="m"),
        sig("branch", 11, branch="main", name="main"),
        sig("request", 15, branch="main", model="m"),
    ]

    rows = session_health(found, KEYS)

    assert [(r["task"], r["requests"], r["agent_s"]) for r in rows] == [(None, 1, 5), ("TASK-7", 2, 10)]


def test_a_launch_branch_names_the_task_until_a_switch_names_another() -> None:
    found = [
        sig("prompt", 0, branch="claude/task-1-a"),
        sig("branch", 3, branch="claude/task-1-a", name="claude/task-2-b"),
        sig("request", 4, branch="claude/task-1-a", model="m"),
    ]

    assert [(r["task"], r["requests"]) for r in session_health(found, KEYS)] == [("TASK-1", 0), ("TASK-2", 1)]


def test_time_is_the_agents_unless_a_human_prompt_ends_it_or_it_idles() -> None:
    found = [
        sig("prompt", 0),
        sig("tool", 30),
        sig("request", 60),
        sig("prompt", 360),  # the operator took 300 s to answer
        sig("request", 380),
        sig("tool", 380 + IDLE_S + 1),  # nothing happened for longer than a turn waits on its own
    ]

    row = only(session_health(found, KEYS))

    assert (row["agent_s"], row["operator_wait_s"], row["idle_s"]) == (60 + 20, 300, IDLE_S + 1)
    assert (row["prompts"], row["operator_prompts"]) == (2, 1)


def test_a_model_or_effort_that_changes_between_main_requests_counts_and_an_unknown_effort_does_not() -> None:
    found = [
        sig("request", 1, model="a", effort=""),
        sig("request", 2, model="a", effort="low"),
        sig("request", 3, model="b", effort="low"),
        sig("request", 4, model="b", effort="high"),
        sig("request", 5, model="c", effort="low", origin="side"),
    ]

    row = only(session_health(found, KEYS))

    assert (row["model_changes"], row["effort_changes"]) == (1, 1)
    assert (row["models"], row["efforts"]) == (["a", "b", "c"], ["low", "high"])
    assert (row["requests"], row["side_requests"]) == (4, 1)


def test_rejections_compactions_skills_and_interrupts_are_counted_by_their_name() -> None:
    found = [
        sig("decision", 1, name="Edit", ok=False, detail="hook"),
        sig("decision", 2, name="Edit", ok=False, detail="user"),
        sig("decision", 3, name="Edit", ok=False, detail="hook"),
        sig("decision", 4, name="Bash", ok=True, detail="config"),
        sig("compaction", 5, name="auto"),
        sig("compaction", 6, name="manual"),
        sig("compaction", 7, name="auto"),
        sig("skill", 8, name="a"),
        sig("skill", 9, name="a"),
        sig("interrupt", 10),
    ]

    row = only(session_health(found, KEYS))

    assert row["rejections"] == {"hook": 2, "user": 1}
    assert row["compactions"] == {"auto": 2, "manual": 1}
    assert (row["skills"], row["interrupts"]) == ({"a": 2}, 1)


def test_a_sessions_kind_is_headless_for_an_sdk_request_and_interactive_for_the_main_thread() -> None:
    headless = [sig("request", 1, session="a", detail="sdk")]
    interactive = [sig("request", 1, session="b", detail="repl_main_thread")]
    unknown = [sig("request", 1, session="c")]

    rows = session_health(headless + interactive + unknown, KEYS)

    assert {r["session"]: r["kind"] for r in rows} == {"a": "headless", "b": "interactive", "c": "unknown"}


def test_a_session_with_no_keys_has_no_task() -> None:
    (row,) = session_health([sig("prompt", 0, branch="claude/task-1-a")], None)

    assert row["task"] is None


def test_a_slice_adds_up_the_sessions_that_worked_its_task() -> None:
    a = [
        sig("prompt", 0, session="a", branch="claude/task-4-x"),
        sig("request", 60, session="a", model="m", effort="low", input=10, output=5, cost=0.5),
        sig("compaction", 61, session="a", name="auto"),
    ]
    b = [
        sig("prompt", 0, session="b", harness=CODEX, branch="claude/task-4-x"),
        sig("prompt", 30, session="b", harness=CODEX, branch="claude/task-4-x"),
        sig("interrupt", 31, session="b", harness=CODEX, branch="claude/task-4-x"),
        sig("request", 60, session="b", harness=CODEX, model="n", effort="high", input=1, output=2, cost=None),
        sig("decision", 61, session="b", harness=CODEX, name="x", ok=False, detail="hook", branch="claude/task-4-x"),
    ]
    other = [sig("prompt", 0, session="c", branch="claude/task-5-y")]

    slices = slice_health(session_health(a + b + other, KEYS))

    four = next(s for s in slices if s["task"] == "TASK-4")
    assert (four["sessions"], four["harnesses"]) == (2, [CLAUDE_CODE, CODEX])
    assert (four["steps"], four["operator_prompts"], four["interrupts"], four["rejections"]) == (2, 1, 1, 1)
    assert (four["interventions"], four["compactions"], four["escalated"], four["clean"]) == (2, 1, False, False)
    assert (four["models"], four["efforts"]) == (["m", "n"], ["low", "high"])
    assert four["tokens"] == {"input": 11, "output": 7, "cache_read": 0, "cache_write": 0, "reasoning": 0}
    assert four["cost_usd"] == 0.5
    assert (four["active_s"], four["operator_wait_s"]) == (61 + 31, 30)


def test_a_slice_of_one_quiet_session_is_clean_and_a_taskless_session_is_no_slice() -> None:
    quiet = [sig("prompt", 0, branch="claude/task-4-x"), sig("request", 5, model="m", effort="low")]
    taskless = [sig("prompt", 0, session="t"), sig("request", 5, session="t", model="m")]

    slices = slice_health(session_health(quiet + taskless, KEYS))

    assert [(s["task"], s["clean"], s["escalated"]) for s in slices] == [("TASK-4", True, False)]


def test_a_slice_whose_model_changed_in_one_session_is_escalated() -> None:
    found = [
        sig("prompt", 0, branch="claude/task-4-x"),
        sig("request", 1, model="a", effort="low"),
        sig("request", 2, model="b", effort="low"),
    ]

    (found_slice,) = slice_health(session_health(found, KEYS))

    assert (found_slice["escalated"], found_slice["clean"]) == (True, False)
