"""The Codex adapter: a recorded rollout and Codex hook payloads become events on the generic harness machine."""

import re
import subprocess
from pathlib import Path

from starpulse._internal.harnesses.codex import CodexAdapter, git_branch
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.kit.adapter_kit import MachineEventsAdapterKit
from starpulse.contracts.adapters import TaskKeys
from starpulse.tests.machines import MACHINES

FIXTURE = Path(__file__).parents[1] / "fixtures" / "codex" / "rollout.jsonl"
SESSION = "00000005-0000-4000-8000-000000000000"
PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"(?:refs/heads/)?feature/(PROJ-\d+)"))


def adapter(branch: str | None = None) -> CodexAdapter:
    return CodexAdapter(keys=PROJ, branch_of=lambda _: branch, clock=lambda: 1_700_000_000.0)


def test_a_recorded_rollout_replays_as_the_harness_machines_event_sequence() -> None:
    events = adapter().rollout(FIXTURE)

    assert [e["event"] for e in events] == [
        "SESSION_STARTED",
        "SKILL_USED",
        "TOOL_USED",
        "TOOL_USED",
        "SESSION_STOPPED",
        "SESSION_STARTED",
        "TOOL_USED",
        "SESSION_STOPPED",
    ]
    assert {(e["machine"], e["run"], e["actor"]) for e in events} == {("harness", SESSION, "codex")}
    assert events[0]["time"] == 1_791_000_001.0
    assert events[1]["time"] == 1_791_000_003.0


def hook(name: str, **fields: object) -> dict:
    return {"hook_event_name": name, "session_id": SESSION, "cwd": "/work/proj", **fields}


def fired(codex: CodexAdapter, payload: dict) -> dict:
    event = codex.hook(payload)
    assert event is not None
    return event


def test_hook_payloads_move_the_machine_through_its_bindings() -> None:
    codex = adapter()

    events = [
        codex.hook(hook("SessionStart")),
        codex.hook(hook("UserPromptSubmit", prompt="go")),
        codex.hook(hook("PostToolUse", tool_name="Bash", tool_input={"command": "git status"})),
        codex.hook(hook("PostToolUse", tool_name="Bash", tool_input={"command": "cat .agents/skills/x/SKILL.md"})),
        codex.hook(hook("Stop")),
    ]

    assert [e["event"] for e in events if e] == [
        "SESSION_STARTED",
        "SESSION_STARTED",
        "TOOL_USED",
        "SKILL_USED",
        "SESSION_STOPPED",
    ]
    assert {e["time"] for e in events if e} == {1_700_000_000.0}


def test_a_hook_the_machine_does_not_bind_moves_nothing() -> None:
    assert adapter().hook(hook("PreToolUse", tool_name="Bash")) is None
    assert adapter().hook({"session_id": SESSION}) is None
    assert adapter().hook(hook("Stop", session_id="")) is None


def test_a_session_on_a_task_branch_is_keyed_by_that_task_else_by_its_run() -> None:
    on_task = fired(adapter("feature/PROJ-123"), hook("Stop"))
    off_task = fired(adapter("main"), hook("Stop"))

    assert (on_task["task"], on_task["run"]) == ("PROJ-123", None)
    assert (off_task["task"], off_task["run"]) == (None, SESSION)


def test_a_working_directorys_branch_is_what_git_has_checked_out(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "feature/PROJ-5-x", str(tmp_path)], check=True, timeout=10)

    assert git_branch(str(tmp_path)) == "feature/PROJ-5-x"
    assert git_branch(str(tmp_path / "missing")) is None


def rollout_of(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "rollout.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


META = '{"timestamp":"2026-10-03T04:00:00.000Z","type":"session_meta","payload":{"id":"s1","cwd":"/work/proj"}}'
STARTED = '{"timestamp":"2026-10-03T04:00:01.000Z","type":"event_msg","payload":{"type":"task_started"}}'


def test_a_rollout_line_that_is_not_a_record_is_skipped_and_the_lines_after_it_are_read(tmp_path: Path) -> None:
    path = rollout_of(
        tmp_path,
        META,
        '{"timestamp":"2026-10-03T04:00:01.000Z","type":"event_msg","payload":{"type":"task_started"',
        "[1]",
        "7",
        '{"type":"event_msg","payload":{"type":"task_started"}}',
        '{"timestamp":"2026-10-03T04:00:01.000Z","payload":{"type":"task_started"}}',
        '{"timestamp":"2026-10-03T04:00:01.000Z","type":"event_msg","payload":"oops"}',
        '{"timestamp":"2026-10-03T04:00:01.000Z","type":"session_meta","payload":[1]}',
        STARTED,
    )

    assert [(e["event"], e["time"]) for e in adapter().rollout(path)] == [("SESSION_STARTED", 1_791_000_001.0)]


def test_a_rollouts_working_directory_is_what_maps_it_to_a_task(tmp_path: Path) -> None:
    codex = CodexAdapter(
        keys=PROJ, branch_of=lambda cwd: "feature/PROJ-4" if cwd == "/work/proj" else None, clock=lambda: 1.0
    )

    [event] = codex.rollout(rollout_of(tmp_path, META, STARTED))

    assert (event["task"], event["run"]) == ("PROJ-4", None)


def test_events_before_the_rollouts_session_or_without_one_name_no_session(tmp_path: Path) -> None:
    anonymous = '{"timestamp":"2026-10-03T04:00:00.000Z","type":"session_meta","payload":{"cwd":"/work/proj"}}'

    assert adapter().rollout(rollout_of(tmp_path, STARTED, META)) == []
    assert adapter().rollout(rollout_of(tmp_path, anonymous, STARTED)) == []


def test_the_branch_of_the_sessions_working_directory_keys_its_events() -> None:
    seen: list[str] = []

    def branch_of(cwd: str) -> str | None:
        seen.append(cwd)
        return "feature/PROJ-8" if cwd == "/work/proj" else None

    codex = CodexAdapter(keys=PROJ, branch_of=branch_of, clock=lambda: 1.0)

    assert fired(codex, hook("Stop"))["task"] == "PROJ-8"
    no_cwd = fired(codex, {"hook_event_name": "Stop", "session_id": SESSION})
    assert (no_cwd["task"], no_cwd["run"]) == (None, SESSION)
    assert seen == ["/work/proj"]


def test_a_rollout_without_a_working_directory_is_keyed_by_its_run(tmp_path: Path) -> None:
    seen: list[str] = []
    codex = CodexAdapter(keys=PROJ, branch_of=lambda cwd: seen.append(cwd) or "feature/PROJ-8", clock=lambda: 1.0)
    path = rollout_of(
        tmp_path, '{"timestamp":"2026-10-03T04:00:00.000Z","type":"session_meta","payload":{"id":"s1"}}', STARTED
    )

    [event] = codex.rollout(path)

    assert (event["task"], event["run"], seen) == (None, "s1", [])


def test_a_hook_name_that_is_not_text_moves_nothing() -> None:
    assert adapter().hook(hook("Stop") | {"hook_event_name": ["Stop"]}) is None


class TestCodexAdapter(MachineEventsAdapterKit):
    keys = PROJ
    branches = {"feature/PROJ-1-add-x": "PROJ-1", "refs/heads/feature/PROJ-2": "PROJ-2", "main": None}
    machines = MACHINES | HARNESS_MACHINES

    def produce(self) -> list[dict]:
        codex = adapter("feature/PROJ-1-add-x")
        return [
            *codex.rollout(FIXTURE),
            fired(codex, hook("SessionStart")),
            fired(adapter("main"), hook("Stop")),
        ]


def test_a_rollout_record_whose_timestamp_is_not_a_time_is_skipped_and_the_rest_replays(tmp_path: Path) -> None:
    path = rollout_of(
        tmp_path,
        META,
        '{"timestamp":"yesterday-ish","type":"event_msg","payload":{"type":"task_started"}}',
        '{"timestamp":1791000001,"type":"event_msg","payload":{"type":"task_started"}}',
        '{"timestamp":null,"type":"event_msg","payload":{"type":"task_started"}}',
        STARTED,
    )

    assert [e["time"] for e in adapter().rollout(path)] == [1_791_000_001.0]


def test_a_rollout_looks_up_a_working_directorys_branch_once_but_the_next_rollout_looks_again(tmp_path: Path) -> None:
    seen: list[str] = []
    codex = CodexAdapter(keys=PROJ, branch_of=lambda cwd: seen.append(cwd) or "feature/PROJ-8", clock=lambda: 1.0)
    path = rollout_of(tmp_path, META, STARTED, STARTED, STARTED)

    events = codex.rollout(path)
    codex.rollout(path)

    assert [e["task"] for e in events] == ["PROJ-8"] * 3
    assert seen == ["/work/proj", "/work/proj"]
