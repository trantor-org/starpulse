"""OTLP log exports of both harnesses read into the signals session and slice health fold.

The recorded fixtures are real exports (Claude Code 2.1.296, Codex 0.154.0) scrubbed of account ids, prompt, reply
and tool-output text; the events no recording holds (a compaction, a Codex skill invocation, an interrupted turn) are
built from the attribute names the harnesses document.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.harnesses.telemetry import CLAUDE_CODE, CODEX, Signal, signals

FIXTURES = Path(__file__).parents[2] / "fixtures"
CLAUDE_SESSION = "11111111-1111-4111-8111-111111111111"
CODEX_SESSION = "22222222-2222-4222-8222-222222222222"


def epoch(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


def recorded(name: str) -> list[Signal]:
    found: list[Signal] = []
    for line in (FIXTURES / name).read_text().splitlines():
        found += signals(json.loads(line))
    return found


def attribute(key: str, value: Any) -> dict:
    if isinstance(value, bool):
        wrapped = {"boolValue": value}
    elif isinstance(value, int):
        wrapped = {"intValue": str(value)}
    elif isinstance(value, float):
        wrapped = {"doubleValue": value}
    else:
        wrapped = {"stringValue": value}
    return {"key": key, "value": wrapped}


def export(*records: dict[str, Any], resource: dict[str, Any] | None = None) -> dict:
    """An OTLP/HTTP logs payload of `records`, each a dict of attributes."""
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": [attribute(k, v) for k, v in (resource or {}).items()]},
                "scopeLogs": [
                    {"logRecords": [{"attributes": [attribute(k, v) for k, v in r.items()]} for r in records]}
                ],
            }
        ]
    }


def claude(name: str, seq: int, at: str = "2026-10-09T10:00:00.000Z", **attrs: Any) -> dict[str, Any]:
    return {"event.name": name, "session.id": "s1", "event.sequence": seq, "event.timestamp": at, **attrs}


def codex(name: str, at: str = "2026-10-09T10:00:00.000Z", **attrs: Any) -> dict[str, Any]:
    return {"event.name": name, "conversation.id": "c1", "event.timestamp": at, **attrs}


def test_a_recorded_claude_code_export_reads_as_prompt_decisions_tools_and_requests() -> None:
    found = recorded("claude_code/otlp.ndjson")

    assert [(s.kind, s.name) for s in found] == [
        ("prompt", ""),
        ("decision", "Bash"),
        ("tool", "Bash"),
        ("request", ""),
        ("decision", "Bash"),
        ("tool", "Bash"),
        ("request", ""),
        ("request", ""),
    ]
    assert {(s.harness, s.session, s.branch) for s in found} == {(CLAUDE_CODE, CLAUDE_SESSION, "claude/task-1-capture")}
    request = found[3]
    assert (request.model, request.effort, request.origin) == ("claude-sonnet-5-5", "medium", "main")
    assert (request.input, request.output, request.cache_read, request.cache_write) == (2, 78, 0, 33489)
    assert (request.cost, request.seconds) == (0.13474, 56.155)
    assert request.time == epoch("2026-10-09T21:27:17.258+00:00")
    tool = found[2]
    assert (tool.ok, tool.seconds) == (False, 0.097)
    assert (found[1].detail, found[1].ok) == ("config", True)


def test_a_recorded_codex_export_reads_as_prompt_requests_and_tools_keyed_by_conversation() -> None:
    found = recorded("codex/otlp.ndjson")

    assert [(s.kind, s.name) for s in found] == [
        ("start", ""),
        ("prompt", ""),
        ("request", ""),
        ("request", ""),
        ("decision", "exec_command"),
        ("tool", "exec_command"),
        ("tool", "exec"),
        ("request", ""),
    ]
    assert {(s.harness, s.session) for s in found} == {(CODEX, CODEX_SESSION)}
    requests = [s for s in found if s.kind == "request"]
    # input_token_count includes the cached tokens; the carve-out leaves the uncached input.
    assert [(r.input, r.output, r.cache_read, r.cache_write, r.reasoning) for r in requests] == [
        (12275, 0, 0, 0, 0),
        (2264, 41, 12032, 0, 0),
        (325, 29, 14080, 0, 22),
    ]
    assert [(r.model, r.effort) for r in requests] == [("gpt-6-astra", "")] + [("gpt-6-astra", "medium")] * 2
    assert found[0].detail == "codex_exec"


def test_nothing_a_user_typed_or_a_tool_ran_is_kept() -> None:
    kept = repr(recorded("claude_code/otlp.ndjson") + recorded("codex/otlp.ndjson"))

    assert "echo" not in kept
    assert "Print" not in kept


def test_codex_names_its_event_in_an_attribute_and_the_log_record_name_is_ignored() -> None:
    payload = export(codex("codex.user_prompt"))
    payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["eventName"] = "something.else"

    assert [s.kind for s in signals(payload)] == ["prompt"]


def test_a_record_with_no_session_or_an_unknown_event_is_skipped() -> None:
    payload = export(
        {"event.name": "user_prompt", "event.timestamp": "2026-10-09T10:00:00Z", "event.sequence": 1},
        claude("plugin_loaded", 2),
        claude("user_prompt", 3),
    )

    assert [s.kind for s in signals(payload)] == ["prompt"]


def test_a_compaction_is_a_signal_with_its_trigger() -> None:
    (found,) = signals(export(claude("compaction", 9, trigger="auto")))

    assert (found.kind, found.name) == ("compaction", "auto")


def test_a_slash_command_names_the_prompt() -> None:
    (found,) = signals(export(claude("user_prompt", 1, command_name="review")))

    assert (found.kind, found.name) == ("prompt", "review")


def test_a_skill_activation_names_the_skill_for_either_harness() -> None:
    claude_skill = signals(export(claude("skill_activated", 4, **{"skill.name": "hello"})))
    codex_skill = signals(export(codex("codex.skill_invocation", **{"skill.name": "hello"})))

    assert [(s.kind, s.name, s.harness) for s in claude_skill + codex_skill] == [
        ("skill", "hello", CLAUDE_CODE),
        ("skill", "hello", CODEX),
    ]


def test_a_rejected_tool_decision_is_not_ok_and_names_its_source() -> None:
    (found,) = signals(export(claude("tool_decision", 5, decision="reject", source="hook", tool_name="Edit")))

    assert (found.kind, found.name, found.ok, found.detail) == ("decision", "Edit", False, "hook")


@pytest.mark.parametrize(
    ("query_source", "origin"),
    [("repl_main_thread", "main"), ("sdk", "main"), ("compact", "auxiliary"), ("code-reviewer", "side")],
)
def test_a_claude_request_is_main_thread_auxiliary_or_a_subagents(query_source: str, origin: str) -> None:
    (found,) = signals(export(claude("api_request", 6, model="m", query_source=query_source)))

    assert (found.kind, found.origin, found.detail) == ("request", origin, query_source)


def test_a_codex_request_from_a_subagent_is_a_side_request_by_its_tools_agent() -> None:
    (main, side) = signals(
        export(
            codex("codex.tool_result", tool_name="exec_command", call_id="a", success="true", agent_name="/root"),
            codex("codex.tool_result", tool_name="exec_command", call_id="b", success="true", agent_name="/root/w1"),
        )
    )

    assert (main.origin, side.origin) == ("main", "side")


def test_a_git_switch_in_a_shell_tool_input_is_a_branch_change() -> None:
    payload = export(
        claude(
            "tool_result",
            7,
            tool_name="Bash",
            success="true",
            tool_input=json.dumps({"command": "git switch -c claude/task-5-x origin/main"}),
        ),
        claude(
            "tool_result",
            8,
            tool_name="Bash",
            success="true",
            tool_input=json.dumps({"command": "git checkout feature/y && make"}),
        ),
        claude("tool_result", 9, tool_name="Bash", success="true", tool_input=json.dumps({"command": "git status"})),
        claude(
            "tool_result", 10, tool_name="Read", success="true", tool_input=json.dumps({"command": "git switch nope"})
        ),
    )

    assert [(s.kind, s.name) for s in signals(payload)] == [
        ("tool", "Bash"),
        ("branch", "claude/task-5-x"),
        ("tool", "Bash"),
        ("branch", "feature/y"),
        ("tool", "Bash"),
        ("tool", "Read"),
    ]


def test_a_codex_interrupted_turn_cost_is_an_interrupt() -> None:
    found = signals(export(codex("codex.turn_cost", **{"turn.interrupted": True, "reasoning_effort": "high"})))

    assert [(s.kind, s.effort) for s in found] == [("interrupt", "high")]


def test_a_launch_branch_on_the_resource_is_every_signals_branch() -> None:
    payload = export(codex("codex.user_prompt"), resource={"vcs.ref.head.name": "claude/task-9-z"})

    assert [s.branch for s in signals(payload)] == ["claude/task-9-z"]


def test_a_record_without_a_timestamp_is_skipped() -> None:
    payload = export({"event.name": "user_prompt", "session.id": "s", "event.sequence": 1})

    assert signals(payload) == []


def test_a_signals_key_is_stable_across_a_replay_and_differs_across_a_resumed_process() -> None:
    first = signals(export(claude("api_request", 0, model="m")))
    replay = signals(export(claude("api_request", 0, model="m")))
    resumed = signals(export(claude("api_request", 0, at="2026-10-09T11:00:00.000Z", model="m")))

    assert first[0].key == replay[0].key
    assert first[0].key != resumed[0].key
