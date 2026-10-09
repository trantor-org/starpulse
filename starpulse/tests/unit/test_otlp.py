"""The OTLP/HTTP JSON a Claude Code export carries, read into the mapper's tool and skill events."""

from __future__ import annotations

import json
from typing import Any

import pytest

from starpulse._internal.adapters.harnesses.otlp import LogEvent, parse


def attr(key: str, value: Any) -> dict[str, Any]:
    match value:
        case bool():
            wrapped = {"boolValue": value}
        case int():
            wrapped = {"intValue": str(value)}  # OTLP JSON carries int64 as a string
        case _:
            wrapped = {"stringValue": value}
    return {"key": key, "value": wrapped}


def payload(*records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": [attr("service.name", "claude-code")]},
                "scopeLogs": [{"logRecords": [{"attributes": attrs} for attrs in records]}],
            }
        ]
    }


def override(key: str, value: Any) -> dict[str, Any]:
    """An attribute override for `tool_result`, typed so a dotted key is not read as a keyword argument."""
    return {key: value}


def tool_result(session: str = "s1", sequence: int = 3, **over: Any) -> list[dict[str, Any]]:
    fields = {
        "event.name": "claude_code.tool_result",
        "session.id": session,
        "event.sequence": sequence,
        "tool_use_id": "toolu_1",
        "tool_name": "Bash",
        "success": "true",
        "tool_input": json.dumps({"command": "git status"}),
        "user.id": "u1",
        **over,
    }
    return [attr(key, value) for key, value in fields.items()]


def test_a_tool_result_is_read_with_its_input_and_success() -> None:
    events = parse(payload(tool_result()))

    assert events == [
        LogEvent(
            session="s1",
            sequence=3,
            kind="tool_result",
            tool_name="Bash",
            tool_use_id="toolu_1",
            success=True,
            tool_input={"command": "git status"},
        )
    ]


def test_success_false_is_read_as_a_failure() -> None:
    (event,) = parse(payload(tool_result(success="false")))

    assert event.success is False


def test_a_skill_activation_carries_the_skill_name() -> None:
    record = [
        attr("event.name", "claude_code.skill_activated"),
        attr("session.id", "s1"),
        attr("event.sequence", 4),
        attr("skill.name", "auditing-docs"),
    ]

    (event,) = parse(payload(record))

    assert (event.kind, event.skill, event.sequence) == ("skill_activated", "auditing-docs", 4)


@pytest.mark.parametrize("prefix", ["", "claude_code."])
def test_tool_and_skill_event_names_may_be_bare_or_prefixed(prefix: str) -> None:
    skill = [
        attr("event.name", f"{prefix}skill_activated"),
        attr("session.id", "s1"),
        attr("event.sequence", 4),
        attr("skill.name", "auditing-docs"),
    ]

    events = parse(payload(tool_result(**override("event.name", f"{prefix}tool_result")), skill))

    assert [(event.kind, event.sequence) for event in events] == [("tool_result", 3), ("skill_activated", 4)]


def test_every_other_log_event_is_dropped() -> None:
    other = tool_result(**override("event.name", "claude_code.api_request"))

    assert parse(payload(other)) == []


@pytest.mark.parametrize("kind", ["user_prompt", "assistant_response"])
def test_a_prompt_and_a_reply_are_kept_with_no_tool_fields(kind: str) -> None:
    record = [attr("event.name", kind), attr("session.id", "s1"), attr("event.sequence", 5), attr("prompt", "secret")]

    assert parse(payload(record)) == [LogEvent(session="s1", sequence=5, kind=kind)]


def test_a_record_carries_its_event_timestamp_as_epoch_seconds() -> None:
    record = tool_result(**override("event.timestamp", "2026-10-03T07:16:01.284Z"))
    no_time = tool_result(**override("event.timestamp", "not a time"))

    assert [event.time for event in parse(payload(record, no_time))] == [1_791_011_761.284, None]


def test_the_branch_an_export_names_in_its_resource_is_on_each_of_its_events() -> None:
    export = payload(tool_result())
    plain = payload(tool_result())
    export["resourceLogs"][0]["resource"]["attributes"].append(attr("vcs.ref.head.name", "feature/PROJ-1"))

    assert [event.branch for event in parse(export) + parse(plain)] == ["feature/PROJ-1", None]


def test_a_record_with_no_session_or_sequence_is_dropped() -> None:
    no_session = [a for a in tool_result() if a["key"] != "session.id"]
    no_sequence = [a for a in tool_result() if a["key"] != "event.sequence"]

    assert parse(payload(no_session, no_sequence)) == []


def test_a_non_numeric_sequence_drops_the_record_instead_of_failing_the_batch() -> None:
    assert parse(payload(tool_result(**override("event.sequence", "soon")), tool_result(sequence=5))) == parse(
        payload(tool_result(sequence=5))
    )


def test_unreadable_tool_input_reads_as_empty_input() -> None:
    (event,) = parse(payload(tool_result(tool_input="{not json")))

    assert event.tool_input == {}


def test_the_event_name_may_come_from_the_body() -> None:
    record = {
        "body": {"stringValue": "claude_code.tool_result"},
        "attributes": tool_result(**override("event.name", "")),
    }

    events = parse({"resourceLogs": [{"scopeLogs": [{"logRecords": [record]}]}]})

    assert [e.kind for e in events] == ["tool_result"]


def test_a_payload_that_is_not_otlp_reads_as_no_events() -> None:
    assert parse({}) == []
    assert parse({"resourceLogs": "x"}) == []


def test_a_skill_activation_has_no_tool_fields() -> None:
    record = [
        attr("event.name", "claude_code.skill_activated"),
        attr("session.id", "s1"),
        attr("event.sequence", 4),
        attr("skill.name", "auditing-docs"),
    ]

    assert parse(payload(record)) == [LogEvent(session="s1", sequence=4, kind="skill_activated", skill="auditing-docs")]


def test_success_may_arrive_as_a_bool_attribute() -> None:
    (ok,) = parse(payload(tool_result(**override("success", True))))
    (failed,) = parse(payload(tool_result(**override("success", False))))

    assert (ok.success, failed.success) == (True, False)


def test_tool_input_that_is_not_an_object_reads_as_empty_input() -> None:
    (array,) = parse(payload(tool_result(tool_input="[1, 2]")))
    (number,) = parse(payload(tool_result(**override("tool_input", 5))))
    absent = [a for a in tool_result() if a["key"] != "tool_input"]

    assert array.tool_input == {}
    assert number.tool_input == {}
    assert parse(payload(absent))[0].tool_input == {}


def test_a_malformed_attribute_does_not_hide_the_ones_around_it() -> None:
    record = {"attributes": ["key", {"value": {"stringValue": "orphan"}}, *tool_result()]}

    events = parse({"resourceLogs": [{"scopeLogs": [{"logRecords": [record]}]}]})

    assert [e.tool_name for e in events] == ["Bash"]


def test_a_record_whose_attributes_are_not_a_list_is_dropped() -> None:
    assert parse({"resourceLogs": [{"scopeLogs": [{"logRecords": [{"attributes": "x"}]}]}]}) == []


def test_malformed_levels_of_the_export_are_skipped_not_fatal() -> None:
    good = {"attributes": tool_result()}
    exports = [
        {"resourceLogs": ["x", {"scopeLogs": ["y", {"logRecords": ["z", good]}]}]},
        {"resourceLogs": [{}, {"scopeLogs": [{}, {"logRecords": [good]}]}]},
        {"resourceLogs": [{"scopeLogs": None}, {"scopeLogs": [{"logRecords": None}, {"logRecords": [good]}]}]},
    ]

    assert [len(parse(export)) for export in exports] == [1, 1, 1]
