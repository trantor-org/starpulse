"""The Claude Code adapter: a recorded OpenTelemetry log export becomes events on the generic harness machine."""

import json
import re
from pathlib import Path

from starpulse._internal.adapters.harnesses.claude_code import ClaudeCodeAdapter, publisher
from starpulse._internal.adapters.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.adapters.harnesses.otlp import BRANCH, LogEvent, parse
from starpulse._internal.api.adapter_kit import MachineEventsAdapterKit
from starpulse.contracts.adapters import TaskKeys
from starpulse._internal.machines.transitions import Table
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse.tests.machines import MACHINES

#: A two-turn session exported with `OTEL_LOG_TOOL_DETAILS=1`, scrubbed of account ids, prompt and reply text.
FIXTURE = Path(__file__).parents[1] / "fixtures" / "claude_code" / "export.ndjson"
SESSION = "00000002-0000-4000-8000-000000000000"
PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"(?:refs/heads/)?feature/(PROJ-\d+)"))


def exports(branch: str | None = None) -> list[dict]:
    payloads = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    for payload in payloads if branch else ():
        for resource in payload["resourceLogs"]:
            resource["resource"]["attributes"].append({"key": BRANCH, "value": {"stringValue": branch}})
    return payloads


def adapter() -> ClaudeCodeAdapter:
    return ClaudeCodeAdapter(keys=PROJ, clock=lambda: 1_700_000_000.0)


def replay(branch: str | None = None) -> list[dict]:
    return [event for payload in exports(branch) for event in adapter().events(parse(payload))]


def test_a_recorded_export_replays_as_the_harness_machines_event_sequence() -> None:
    events = replay()

    assert [e["event"] for e in events] == [
        "SESSION_STARTED",  # turn 1: the prompt
        "SKILL_USED",  # the hello skill; its Skill tool result maps to nothing
        "TOOL_USED",  # a failed `ls`
        "SESSION_STOPPED",  # the reply
        "SESSION_STARTED",  # turn 2, in a resumed process whose event.sequence restarts at 0
        "SESSION_STOPPED",  # a reply mid-turn, before the tool call it announces
        "TOOL_USED",
        "SESSION_STOPPED",
        "TOOL_USED",
        "SESSION_STOPPED",
    ]
    assert {(e["machine"], e["task"], e["run"], e["actor"]) for e in events} == {
        ("harness", None, SESSION, "claude-code")
    }
    assert events[0]["time"] == 1_791_011_759.765


def test_the_branch_an_export_names_keys_its_events_to_that_task() -> None:
    assert {(e["task"], e["run"]) for e in replay("feature/PROJ-7-x")} == {("PROJ-7", None)}
    assert {(e["task"], e["run"]) for e in replay("main")} == {(None, SESSION)}


def test_a_record_without_a_timestamp_takes_the_adapters_clock() -> None:
    [event] = adapter().events([LogEvent(session="s1", sequence=1, kind="user_prompt")])

    assert event["time"] == 1_700_000_000.0


def test_a_skill_tool_result_moves_nothing_since_its_activation_already_did() -> None:
    skill = LogEvent(session="s1", sequence=2, kind="tool_result", tool_name="Skill", time=1.0)
    read = LogEvent(session="s1", sequence=3, kind="tool_result", tool_name="Read", time=2.0)

    assert [e["event"] for e in adapter().events([skill, read])] == ["TOOL_USED"]


def test_activity_after_a_mid_turn_reply_draws_the_session_active_again() -> None:
    table = Table(HARNESS_MACHINES["harness"])

    assert [table.target("stopped", event) for event in ("TOOL_USED", "SKILL_USED", "SESSION_STARTED")] == [
        "active",
        "active",
        "active",
    ]


class TestClaudeCodeAdapter(MachineEventsAdapterKit):
    keys = PROJ
    branches = {"feature/PROJ-1-add-x": "PROJ-1", "refs/heads/feature/PROJ-2": "PROJ-2", "main": None}
    machines = MACHINES | HARNESS_MACHINES

    def produce(self) -> list[dict]:
        return [*replay("feature/PROJ-1-add-x"), *replay()]


def test_the_publisher_appends_each_mapped_event_to_the_log_under_the_machine_events_stream(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    publish = publisher(log)

    for event in replay("feature/PROJ-7-x")[:2]:
        assert publish(event) is not None

    assert [(e.fields["event"], e.fields["task"], e.fields["actor"]) for e in Tail(log, "machine:events").poll()] == [
        ("SESSION_STARTED", "PROJ-7", "claude-code"),
        ("SKILL_USED", "PROJ-7", "claude-code"),
    ]
