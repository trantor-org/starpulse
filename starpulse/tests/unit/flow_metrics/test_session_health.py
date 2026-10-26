"""Session health and slice health: folds of harness telemetry signals, worked out by hand on recorded exports."""

import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from starpulse._internal.config.analytics import Analytics
from starpulse._internal.signals import claim_key
from starpulse.contracts.adapters import TaskKeys
from starpulse.flow_metrics.session_health import grouped, session_health, session_rows, slice_health
from starpulse.harness_telemetry.telemetry import CLAUDE_CODE, CODEX, Signal, signals
from starpulse.tests.unit.harness_telemetry.test_telemetry import FIXTURES, claude, export, recorded

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
    # the three model requests (56.155 + 1.778 + 1.577) and the two commands (0.097 + 0.032), not the export's span
    assert row["agent_s"] == pytest.approx(59.639)
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
    # Codex exports no request duration, so its agent seconds are its two commands' (0.784 + 1.657) alone
    assert row["agent_s"] == pytest.approx(2.441)


def test_the_recorded_older_export_counts_its_skill_and_its_two_turns() -> None:
    found: list[Signal] = []
    for line in (FIXTURES / "claude_code" / "export.ndjson").read_text().splitlines():
        found += signals(json.loads(line))

    row = only(session_health(found, KEYS))

    assert (row["prompts"], row["operator_prompts"], row["skills"]) == (2, 1, {"hello": 1})


def test_a_git_switch_to_a_task_branch_names_the_session_before_it_and_a_trip_back_to_main_drops_nothing() -> None:
    found = [
        sig("prompt", 0, branch="main"),
        sig("request", 5, branch="main", model="m", seconds=5),
        sig("branch", 6, branch="main", name="claude/task-7-x"),
        sig("request", 10, branch="main", model="m", seconds=4),
        sig("branch", 11, branch="main", name="main"),
        sig("request", 15, branch="main", model="m", seconds=6),
    ]

    rows = session_health(found, KEYS)

    assert [(r["task"], r["requests"], r["agent_s"]) for r in rows] == [("TASK-7", 3, 15)]


def test_signals_before_the_first_claim_of_a_session_on_a_taskless_branch_belong_to_the_claimed_task() -> None:
    found = [
        sig("prompt", 0, branch="main", turn="p1", detail="human"),
        sig("request", 5, branch="main", model="m", seconds=5, turn="p1"),
        sig("claim", 6, branch="main", name="TASK-3", turn="p1"),
        sig("request", 10, branch="main", model="m", seconds=4, turn="p1"),
    ]

    row = only(session_health(found, KEYS))

    assert (row["task"], row["prompts"], row["requests"], row["agent_s"]) == ("TASK-3", 1, 2, 9)


def test_a_launch_branch_names_the_task_until_a_switch_names_another() -> None:
    found = [
        sig("prompt", 0, branch="claude/task-1-a"),
        sig("branch", 3, branch="claude/task-1-a", name="claude/task-2-b"),
        sig("request", 4, branch="claude/task-1-a", model="m"),
    ]

    assert [(r["task"], r["requests"]) for r in session_health(found, KEYS)] == [("TASK-1", 0), ("TASK-2", 1)]


def test_time_is_the_summed_durations_and_the_wait_before_a_human_prompt_never_the_silence_inside_a_turn() -> None:
    found = [
        sig("prompt", 0),
        sig("tool", 30, seconds=10),
        sig("request", 60, seconds=20),
        sig("prompt", 360),  # the operator took 300 s to answer
        sig("request", 380, seconds=20),
        sig("tool", 2000, seconds=5),  # a long silence inside a turn is the model's or a tool's, never idle
    ]

    row = only(session_health(found, KEYS))

    assert (row["agent_s"], row["operator_wait_s"], row["idle_s"]) == (10 + 20 + 20 + 5, 300, 0)
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
    assert (row["main_model"], row["main_effort"]) == ("a", "low")


def test_a_side_request_before_the_first_main_request_does_not_set_the_main_model() -> None:
    found = [
        sig("request", 1, model="title", effort="low", origin="side"),
        sig("request", 2, model="big", effort="high"),
    ]

    row = only(session_health(found, KEYS))

    assert (row["models"], row["main_model"], row["main_effort"]) == (["title", "big"], "big", "high")


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


def test_the_first_human_prompt_after_a_main_thread_reply_that_opens_with_a_question_is_no_operator_prompt() -> None:
    found = [
        sig("prompt", 0, detail="human", branch="claude/task-4-x"),
        sig("reply", 10, detail="asks"),
        sig("prompt", 20, detail="injected"),  # a notification does not answer it
        sig("prompt", 30, detail="human", label="approval"),  # the answer
        sig("prompt", 40, detail="human", label="correction"),
        sig("reply", 50, detail=""),
        sig("prompt", 60, detail="human"),
        sig("reply", 70, detail="asks", origin="side"),  # a subagent's question is not the operator's to answer
        sig("prompt", 80, detail="human"),
    ]

    row = only(session_health(found, KEYS))
    (health,) = slice_health([row])

    assert row["prompts"] == 6
    assert row["operator_prompts"] == 3
    assert row["prompt_labels"] == {"correction": 1}
    assert (health["interventions"], health["clean"]) == (3, False)


def test_operator_prompts_are_counted_by_the_label_the_labeller_gave_them_and_user_rejects_apart_from_hook_ones() -> (
    None
):
    found = [
        sig("prompt", 0, detail="human", label="request", branch="claude/task-4-x"),  # the first prompt is not steering
        sig("prompt", 10, detail="human", label="correction"),
        sig("prompt", 20, detail="human", label="correction"),
        sig("prompt", 30, detail="human", label="approval"),
        sig("prompt", 40, detail="human"),  # no labeller answered
        sig("prompt", 50, detail="injected"),
        sig("decision", 60, name="Edit", ok=False, detail="user_reject"),
        sig("decision", 61, name="Bash", ok=False, detail="user_abort"),
        sig("decision", 62, name="Bash", ok=False, detail="hook"),
        sig("decision", 63, name="Bash", ok=True, detail="user_reject"),
    ]

    row = only(session_health(found, KEYS))
    (health,) = slice_health([row])

    assert row["operator_prompts"] == 4
    assert row["prompt_labels"] == {"correction": 2, "approval": 1}
    assert row["user_rejects"] == 2
    assert (health["prompt_labels"], health["user_rejects"]) == ({"correction": 2, "approval": 1}, 2)
    assert (health["operator_prompts"], health["interventions"], health["clean"]) == (4, 4, False)


def test_a_rejection_is_also_counted_by_the_gate_that_refused_it_as_source_and_tool() -> None:
    found = [
        sig("decision", 1, name="Bash", ok=False, detail="hook"),
        sig("decision", 2, name="Edit", ok=False, detail="hook"),
        sig("decision", 3, name="Bash", ok=False, detail="hook"),
        sig("decision", 4, name="Bash", ok=False, detail="user"),
        sig("decision", 5, name="Bash", ok=False, detail=""),
        sig("decision", 6, name="Bash", ok=True, detail="hook"),
    ]

    row = only(session_health(found, KEYS))

    assert row["gates"] == {"hook:Bash": 2, "hook:Edit": 1, "user:Bash": 1, "unknown:Bash": 1}
    assert sum(row["gates"].values()) == sum(row["rejections"].values())


def test_a_sessions_kind_is_headless_for_an_sdk_request_and_interactive_for_the_main_thread() -> None:
    headless = [sig("request", 1, session="a", detail="sdk")]
    interactive = [sig("request", 1, session="b", detail="repl_main_thread")]
    unknown = [sig("request", 1, session="c")]

    rows = session_health(headless + interactive + unknown, KEYS)

    assert {r["session"]: r["kind"] for r in rows} == {"a": "headless", "b": "interactive", "c": "unknown"}


def test_a_main_thread_request_under_a_custom_output_style_is_counted_as_a_main_request_not_a_side_one() -> None:
    sources = ["repl_main_thread:outputStyle:custom", "generate_session_title", "compact"]
    found = signals(export(*(claude("api_request", n, model="m", query_source=q) for n, q in enumerate(sources))))

    row = only(session_health(found, KEYS))

    assert (row["requests"], row["side_requests"]) == (1, 1)


def test_a_sessions_kind_is_interactive_for_a_main_thread_request_under_a_custom_output_style() -> None:
    styled = [sig("request", 1, detail="repl_main_thread:outputStyle:custom")]
    other = [sig("request", 1, session="b", detail="repl_main_threads")]

    rows = session_health(styled + other, KEYS)

    assert {r["session"]: r["kind"] for r in rows} == {"s": "interactive", "b": "unknown"}


def test_a_session_with_no_keys_has_no_task() -> None:
    (row,) = session_health([sig("prompt", 0, branch="claude/task-1-a")], None)

    assert row["task"] is None


def test_a_slice_adds_up_the_sessions_that_worked_its_task() -> None:
    a = [
        sig("prompt", 0, session="a", branch="claude/task-4-x"),
        sig("request", 60, session="a", model="m", effort="low", input=10, output=5, cost=0.5, seconds=60),
        sig("compaction", 61, session="a", name="auto"),
    ]
    b = [
        sig("prompt", 0, session="b", harness=CODEX, branch="claude/task-4-x"),
        sig("prompt", 30, session="b", harness=CODEX, branch="claude/task-4-x"),
        sig("interrupt", 31, session="b", harness=CODEX, branch="claude/task-4-x"),
        sig(
            "request",
            60,
            session="b",
            harness=CODEX,
            model="n",
            effort="high",
            input=1,
            output=2,
            cost=None,
            seconds=31,
        ),
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
    assert (four["active_s"], four["operator_wait_s"]) == (60 + 31, 30)


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


def test_a_mid_session_move_up_the_ladder_is_a_raise_and_a_move_down_a_lowering() -> None:
    found = [
        sig("prompt", 0, branch="claude/task-4-x"),
        sig("request", 1, model="claude-sonnet-5", effort="high"),
        sig("request", 2, model="claude-opus-5", effort="low"),
        sig("request", 3, model="claude-haiku-5", effort="low"),
        sig("request", 4, model="claude-haiku-5", effort="medium"),
    ]

    (found_slice,) = slice_health(session_health(found, KEYS))

    assert (found_slice["raises"], found_slice["lowers"]) == (2, 1)


def by_task(rows: list[dict], field: str) -> dict[tuple[str, str | None], object]:
    return {(r["session"], r["task"]): r[field] for r in rows}


def test_a_first_claim_covers_the_steps_before_it_a_later_one_only_those_after_and_no_claim_leaves_none() -> None:
    claimed = [
        sig("prompt", 0, turn="p1"),
        sig("request", 5, model="m"),
        sig("claim", 6, name="TASK-1"),
        sig("request", 10, model="m"),
        sig("request", 12, model="m"),
        sig("claim", 20, name="TASK-2"),
        sig("request", 25, model="m"),
    ]
    unclaimed = [sig("prompt", 0, session="n", turn="q1"), sig("request", 3, session="n", model="m")]

    rows = session_health(claimed + unclaimed, KEYS)

    assert by_task(rows, "requests") == {("s", "TASK-1"): 3, ("s", "TASK-2"): 1, ("n", None): 1}


START_CLAIMS = Analytics(claims=(re.compile(r"board_task\.py\s+start\s+(TASK-\d+)"),))


def test_a_stored_shell_command_the_claims_match_attributes_the_whole_session_to_its_task_with_no_claim_row() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("request", 1, model="m"),
        sig("tool", 2, name="Bash", command="bin/board_task.py start TASK-7"),
        sig("request", 3, model="m"),
        sig("request", 4, model="m"),
    ]

    rows = session_health(found, KEYS, START_CLAIMS)

    # the first claim covers the steps before it, as a stored claim row would
    assert by_task(rows, "requests") == {("s", "TASK-7"): 3}
    assert by_task(rows, "tool_calls") == {("s", "TASK-7"): 1}


def test_a_tool_result_with_a_stored_claim_row_and_a_matching_command_is_one_claim() -> None:
    tool = sig("tool", 2, name="Bash", command="bin/board_task.py start TASK-7")
    stored = replace(sig("claim", 2, name="TASK-7"), key=claim_key(tool.key))
    unstored = sig("tool", 5, name="Bash", command="bin/board_task.py start TASK-8")
    found = [sig("request", 1, model="m"), tool, stored, sig("request", 3, model="m"), unstored]

    [ordered] = grouped(found, KEYS, START_CLAIMS)

    assert [(s.name, s.key) for s in ordered if s.kind == "claim"] == [
        ("TASK-7", claim_key(tool.key)),
        ("TASK-8", claim_key(unstored.key)),
    ]


def test_without_a_claims_pattern_or_a_task_key_scheme_a_stored_command_claims_nothing() -> None:
    found = [sig("tool", 2, name="Bash", command="bin/board_task.py start TASK-7")]

    assert [s.kind for [ordered] in [grouped(found, KEYS, Analytics())] for s in ordered] == ["tool"]
    assert [s.kind for [ordered] in [grouped(found, None, START_CLAIMS)] for s in ordered] == ["tool"]
    # a command naming something the board's scheme does not call a task is no claim
    other = [sig("tool", 2, name="Bash", command="bin/board_task.py start NOTE-7")]
    assert [
        s.kind
        for [ordered] in [grouped(other, KEYS, Analytics(claims=(re.compile(r"start\s+(\S+)"),)))]
        for s in ordered
    ] == ["tool"]


def test_a_hooks_run_time_inside_a_turn_is_agent_time() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("request", 10, turn="p1", seconds=8.0),
        sig("hook", 12, turn="p1", seconds=1.5, name="PreToolUse:Bash"),
        sig("tool", 13, turn="p1", seconds=0.5),
        sig("hook", 15, turn="p1", seconds=1.5, name="PostToolUse:Bash"),
        sig("reply", 20, turn="p1"),
    ]

    assert only(session_health(found, KEYS))["agent_s"] == 8.0 + 1.5 + 0.5 + 1.5


def test_agent_seconds_are_the_summed_api_and_tool_durations_and_a_twenty_minute_prompt_gap_is_the_operators() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("request", 40, turn="p1", seconds=30.0),
        sig("tool", 41, turn="p1", seconds=1.5),
        sig("request", 60, turn="p1", seconds=15.0),
        sig("reply", 61, turn="p1"),
        sig("prompt", 61 + 1200, turn="p2", detail="human"),
        sig("request", 1270, turn="p2", seconds=8.0),
        sig("reply", 1271, turn="p2"),
    ]

    row = only(session_health(found, KEYS))

    assert row["agent_s"] == 30.0 + 1.5 + 15.0 + 8.0
    assert (row["operator_wait_s"], row["idle_s"]) == (1200, 0)


def test_a_prompt_typed_while_the_last_turn_still_worked_waits_for_nothing_and_an_injected_one_idles() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("request", 30, turn="p1", seconds=30.0),
        sig("prompt", 50, turn="p2", detail="human"),  # typed while p1 still ran
        sig("tool", 90, turn="p1", seconds=5.0),
        sig("reply", 91, turn="p2"),
        sig("prompt", 191, turn="p3", detail="injected"),  # a background task's notice, 100 s after the last turn
        sig("reply", 192, turn="p3"),
    ]

    row = only(session_health(found, KEYS))

    assert (row["operator_wait_s"], row["idle_s"]) == (0, 100)


ASKS = Analytics(operator_tools=frozenset({"AskUserQuestion"}))


def _asked(*, tool: str = "AskUserQuestion", source: str = "user_temporary") -> list[Signal]:
    """A turn whose last request ends at 40 s, then the operator answers a question 1575 s later."""
    return [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("request", 40, turn="p1", seconds=30.0),
        sig("decision", 1615, turn="p1", name=tool, ok=True, detail=source),
        sig("tool", 1615.02, turn="p1", name=tool, seconds=0.004),
        sig("request", 1620, turn="p1", seconds=4.0),
        sig("reply", 1621, turn="p1"),
    ]


def test_the_silence_before_an_operator_tool_result_is_the_operators_wait_and_not_agent_time() -> None:
    row = only(session_health(_asked(), KEYS, ASKS))

    assert row["operator_wait_s"] == pytest.approx(1615.02 - 0.004 - 40)
    assert row["agent_s"] == pytest.approx(30.0 + 0.004 + 4.0)
    assert row["idle_s"] == 0


def test_a_question_answered_by_a_hook_waits_for_nothing_and_a_tool_the_config_does_not_name_is_not_a_question() -> (
    None
):
    answered = _asked(source="hook")
    answered[2] = replace(answered[2], time=answered[1].time + 1)  # a hook answers at once
    answered[3] = replace(answered[3], time=answered[1].time + 1.02)

    assert only(session_health(answered, KEYS, ASKS))["operator_wait_s"] < 1.1
    assert only(session_health(_asked(tool="Bash"), KEYS, ASKS))["operator_wait_s"] == 0
    assert only(session_health(_asked(), KEYS))["operator_wait_s"] == 0


def test_the_wait_before_a_question_and_the_prompt_after_it_are_each_charged_once() -> None:
    found = [*_asked(), sig("prompt", 1621 + 300, turn="p2", detail="human"), sig("reply", 1923, turn="p2")]

    row = only(session_health(found, KEYS, ASKS))

    assert row["operator_wait_s"] == pytest.approx(1615.02 - 0.004 - 40 + 300)


def test_a_turn_with_no_closing_reply_is_an_interrupt_and_a_loaded_skill_then_a_deliver_is_complete() -> None:
    analytics = Analytics(completion_skill="completing-tasks")
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("reply", 5, turn="p1"),
        sig("prompt", 10, turn="p2", detail="human"),  # the operator stopped it: no reply
        sig("prompt", 20, turn="p3", detail="human"),
        sig("skill", 21, turn="p3", name="completing-tasks"),
        sig("deliver", 22, turn="p3"),
        sig("reply", 23, turn="p3"),
    ]
    delivered_without_the_skill = [sig("prompt", 0, session="d", turn="q"), sig("deliver", 1, session="d", turn="q")]

    rows = session_health(found + delivered_without_the_skill, KEYS, analytics)

    assert by_task(rows, "interrupts") == {("s", None): 1, ("d", None): 1}
    assert by_task(rows, "complete") == {("s", None): True, ("d", None): False}


def test_a_codex_prompt_with_no_reply_is_not_an_interrupt() -> None:
    found = [sig("prompt", 0, harness=CODEX), sig("request", 5, harness=CODEX, model="m")]

    assert only(session_health(found, KEYS))["interrupts"] == 0


def test_human_prompts_after_a_claim_and_the_steps_before_the_first_edit_are_counted() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),  # the start prompt, before the claim
        sig("claim", 3, name="TASK-9", turn="p1"),
        sig("request", 4, model="m", turn="p1"),
        sig("request", 5, model="m", origin="side", agent="Explore", turn="p1"),
        sig("tool", 6, name="Read", turn="p1"),
        sig("request", 7, model="m", turn="p1"),
        sig("tool", 8, name="Edit", turn="p1"),
        sig("request", 9, model="m", turn="p1"),
        sig("reply", 10, turn="p1"),
        sig("prompt", 20, turn="p2", detail="human"),
        sig("prompt", 21, turn="p3", detail="injected"),
        sig("prompt", 22, turn="p4", detail="human"),
    ]

    rows = {r["task"]: r for r in session_health(found, KEYS)}

    assert list(rows) == ["TASK-9"]
    assert (rows["TASK-9"]["operator_prompts"], rows["TASK-9"]["steps_before_edit"]) == (2, 3)


def test_a_shell_command_that_writes_a_file_is_the_first_edit() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("claim", 1, name="TASK-9", turn="p1"),
        sig("request", 2, model="m", turn="p1"),
        sig("tool", 3, name="Bash", command="rg -n foo", turn="p1"),
        sig("request", 4, model="m", turn="p1"),
        sig("tool", 5, name="Bash", command="cat > a.py", shell_write=True, turn="p1"),
        sig("request", 6, model="m", turn="p1"),
        sig("reply", 7, turn="p1"),
    ]

    assert only(session_health(found, KEYS))["steps_before_edit"] == 2


def test_a_failed_shell_write_is_not_the_first_edit() -> None:
    found = [
        sig("prompt", 0, turn="p1", detail="human"),
        sig("claim", 1, name="TASK-9", turn="p1"),
        sig("request", 2, model="m", turn="p1"),
        sig("tool", 3, name="Bash", command="echo x > a.txt", shell_write=True, ok=False, turn="p1"),
        sig("reply", 4, turn="p1"),
    ]

    assert only(session_health(found, KEYS))["steps_before_edit"] is None


def test_one_session_folds_to_one_row_per_task_it_worked_in_the_order_it_reached_them() -> None:
    ordered = [
        sig("prompt", 0, branch="claude/task-1-a"),
        sig("request", 10, model="m", effort="low", input=3, seconds=10),
        sig("branch", 20, name="claude/task-2-b"),
        sig("request", 30, model="m", effort="low", input=4, seconds=5),
    ]

    rows = session_rows(ordered, KEYS, None)

    assert [(r["task"], r["requests"], r["tokens"]["input"]) for r in rows] == [("TASK-1", 1, 3), ("TASK-2", 1, 4)]


def test_session_rows_of_one_session_is_what_session_health_gives_for_it() -> None:
    found = [sig("prompt", 0, branch="claude/task-1-a"), sig("request", 5, model="m", seconds=5)]

    assert session_rows(grouped(found)[0], KEYS, None) == session_health(found, KEYS)


def test_no_doc_lists_starpulse_insights() -> None:
    docs = Path(__file__).resolve().parents[4] / "docs"
    assert [path.name for path in docs.glob("*.md") if "starpulse_insights" in path.read_text()] == []


def test_a_session_row_names_the_eval_run_its_signals_came_from() -> None:
    at = "2026-10-09T11:00:00.000Z"
    evaluated = signals(export(claude("api_request", 0, at, model="m"), resource={"trantor.eval": "judge"}))
    plain = signals(export(claude("api_request", 0, at, model="m", **{"session.id": "s2"})))

    assert sorted(row["eval"] for row in session_health(evaluated + plain, None)) == ["", "judge"]
