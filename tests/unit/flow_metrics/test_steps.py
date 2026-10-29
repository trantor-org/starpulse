"""Per-step records: one row per model request, with the skill in force, the calls it made and its tokens."""

import json
import re

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.flow_metrics.model.steps import session_steps
from starpulse.harness_telemetry.adapters.inbound.telemetry import signals

from tests.unit.harness_telemetry.test_telemetry import claude, codex, export

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
BRANCH = {"vcs.ref.head.name": "claude/task-7-x"}


def stream(*records: dict, redact=None) -> list:
    """The signals of an OTLP logs payload of `records`."""
    return signals(export(*records, resource=BRANCH), redact)


def request(seq: int, at: str, *, session: str = "s1", seconds: float = 1.0, **attrs: object) -> dict:
    return claude(
        "api_request",
        seq,
        at,
        **{"session.id": session, "duration_ms": int(seconds * 1000), "model": "claude-sonnet-5-5"},
        **attrs,
    )


def result(seq: int, at: str, tool: str, *, session: str = "s1", seconds: float = 0.1, **attrs: object) -> dict:
    return claude(
        "tool_result",
        seq,
        at,
        **{"session.id": session, "tool_name": tool, "success": True, "duration_ms": int(seconds * 1000)},
        **attrs,
    )


def test_each_model_request_is_one_step_with_its_task_tokens_and_no_skill_before_a_load() -> None:
    found = stream(
        request(1, "2026-10-09T10:00:01.000Z", input_tokens=10, output_tokens=2, cache_read_tokens=100),
        request(2, "2026-10-09T10:00:05.000Z", session="s2", input_tokens=7, output_tokens=1, cache_creation_tokens=9),
    )

    one, two = session_steps(found, KEYS)

    assert (one["session"], one["task"], one["model"], one["skill"]) == ("s1", "TASK-7", "claude-sonnet-5-5", "none")
    assert one["tokens"] == {"input": 10, "output": 2, "cache_read": 100, "cache_write": 0, "reasoning": 0}
    assert (two["session"], two["skill"], two["tokens"]["cache_write"]) == ("s2", "none", 9)
    assert (one["harness"], one["captured"], one["origin"], one["activities"], one["keys"]) == (
        "claude-code",
        True,
        "main",
        [],
        [],
    )


def test_a_step_carries_the_activities_and_keys_of_the_calls_it_made_and_a_redacted_command() -> None:
    found = stream(
        request(1, "2026-10-09T10:00:01.000Z"),
        result(2, "2026-10-09T10:00:02.000Z", "Bash", tool_input='{"command":"git status -sb"}'),
        result(3, "2026-10-09T10:00:02.100Z", "Read"),
        request(4, "2026-10-09T10:00:04.000Z"),
        redact=lambda text: text.upper(),
    )

    first, second = session_steps(found, KEYS)

    assert first["activities"] == ["git status", "Read"]
    assert first["keys"] == ["GIT STATUS -SB", "Read"]
    assert (second["activities"], second["keys"]) == ([], [])


def test_a_stream_of_two_sessions_is_one_step_per_request_with_each_sessions_own_skill_work_and_tokens() -> None:
    found = stream(
        request(1, "2026-10-09T10:00:01.000Z", session="a", input_tokens=10, output_tokens=2),
        result(2, "2026-10-09T10:00:01.200Z", "Read", session="a"),
        request(3, "2026-10-09T10:00:03.000Z", session="b", input_tokens=5, output_tokens=1),
        result(4, "2026-10-09T10:00:03.200Z", "Skill", session="b"),
        claude("skill_activated", 5, "2026-10-09T10:00:03.201Z", **{"session.id": "b", "skill.name": "alpha"}),
        request(6, "2026-10-09T10:00:05.000Z", session="a", input_tokens=7, output_tokens=3),
        request(7, "2026-10-09T10:00:07.000Z", session="b", input_tokens=2, output_tokens=2),
    )

    steps = session_steps(found, KEYS)

    assert [(s["session"], s["task"], s["skill"], s["activities"], s["keys"]) for s in steps] == [
        ("a", "TASK-7", "none", ["Read"], ["Read"]),
        ("b", "TASK-7", "alpha", ["Skill"], ["Skill"]),
        ("a", "TASK-7", "none", [], []),
        ("b", "TASK-7", "alpha", [], []),
    ]
    assert [(s["tokens"]["input"], s["tokens"]["output"]) for s in steps] == [(10, 2), (5, 1), (7, 3), (2, 2)]


def test_a_skill_is_in_force_from_the_step_that_loads_it_until_the_next_load() -> None:
    found = stream(
        request(1, "2026-10-09T10:00:00.500Z"),
        request(2, "2026-10-09T10:00:01.000Z"),
        result(3, "2026-10-09T10:00:02.000Z", "Skill"),
        claude("skill_activated", 4, "2026-10-09T10:00:02.001Z", **{"skill.name": "alpha"}),
        request(5, "2026-10-09T10:00:04.000Z"),
        request(6, "2026-10-09T10:00:07.000Z"),
        claude("skill_activated", 7, "2026-10-09T10:00:08.000Z", **{"skill.name": "beta"}),
        request(8, "2026-10-09T10:00:11.000Z"),
    )

    steps = session_steps(found, KEYS)

    assert [s["skill"] for s in steps] == ["none", "alpha", "alpha", "beta", "beta"]
    assert [s["activities"] for s in steps] == [[], ["Skill"], [], [], []]


def test_a_call_logged_before_its_own_request_still_belongs_to_that_request() -> None:
    # The request logged at 02.5 had been streaming since 01.0: the Skill result and its load at 02.0 came first, and
    # still belong to it. The Bash result at 03.0 started after no other request did, so it is that request's too.
    found = stream(
        request(1, "2026-10-09T10:00:02.500Z", seconds=1.5),
        request(4, "2026-10-09T10:00:00.500Z", seconds=0.5),
        result(2, "2026-10-09T10:00:02.000Z", "Skill"),
        claude("skill_activated", 3, "2026-10-09T10:00:02.001Z", **{"skill.name": "alpha"}),
        result(5, "2026-10-09T10:00:03.000Z", "Bash"),
    )

    early, loader = session_steps(found, KEYS)

    assert (early["skill"], early["activities"]) == ("none", [])
    assert (loader["skill"], loader["activities"]) == ("alpha", ["Skill", "Bash"])


def test_a_result_after_a_request_ended_belongs_to_it_and_not_to_the_next_request() -> None:
    found = stream(
        request(1, "2026-10-09T10:00:01.000Z"),
        result(2, "2026-10-09T10:00:01.200Z", "Read"),
        request(3, "2026-10-09T10:00:03.000Z"),
    )

    first, second = session_steps(found, KEYS)

    assert (first["activities"], second["activities"]) == (["Read"], [])


def test_a_load_before_any_request_of_the_window_is_in_force_for_the_first_step() -> None:
    found = stream(
        claude("skill_activated", 1, "2026-10-09T10:00:00.500Z", **{"skill.name": "alpha"}),
        request(2, "2026-10-09T10:00:02.000Z"),
    )

    (step,) = session_steps(found, KEYS)

    assert step["skill"] == "alpha"


def test_a_codex_step_is_kept_and_marked_not_captured() -> None:
    def completed(at: str, **attrs: object) -> dict:
        return codex("codex.sse_event", at, **{"event.kind": "response.completed", "model": "gpt-5", **attrs})

    found = signals(
        export(
            completed("2026-10-09T10:00:01.000Z", input_token_count=12),
            completed("2026-10-09T10:00:03.000Z", output_token_count=3),
            codex("codex.skill_invocation", "2026-10-09T10:00:04.000Z", **{"skill.name": "alpha"}),
            completed("2026-10-09T10:00:05.000Z"),
        )
    )

    first, second, third = session_steps(found, KEYS)

    assert (first["harness"], first["captured"], first["skill"], first["tokens"]["input"]) == (
        "codex",
        False,
        "none",
        12,
    )
    assert (second["skill"], second["tokens"]["output"], third["skill"]) == ("alpha", 3, "alpha")


def test_a_command_stored_before_the_claims_were_declared_gives_the_session_its_task() -> None:
    found = signals(
        export(
            request(1, "2026-10-09T10:00:01.000Z"),
            result(
                2,
                "2026-10-09T10:00:02.000Z",
                "Bash",
                tool_input=json.dumps({"command": "bin/board_task.py start TASK-9"}),
            ),
            request(3, "2026-10-09T10:00:05.000Z"),
        ),
        lambda command: command,
    )
    claims = Analytics(claims=(re.compile(r"board_task\.py\s+start\s+(TASK-\d+)"),))

    assert [s["task"] for s in session_steps(found, KEYS)] == [None, None]
    assert [s["task"] for s in session_steps(found, KEYS, claims)] == ["TASK-9", "TASK-9"]


def test_a_step_names_the_eval_run_that_made_its_request_and_is_empty_for_any_other() -> None:
    resource = {**BRANCH, "trantor.eval": "judge"}
    evaluated = signals(
        export(request(0, "2026-10-09T11:00:00.000Z"), resource=resource),
        analytics=Analytics(eval_attribute="trantor.eval"),
    )
    plain = signals(export(request(0, "2026-10-09T11:00:00.000Z", session="s2")))

    assert [step["eval"] for step in session_steps(evaluated + plain, KEYS)] == ["judge", ""]
