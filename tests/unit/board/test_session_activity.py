"""A session's activity read from its transcript: `idle` after a finished turn, `working` mid-turn."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starpulse.board.adapters.session_activity import holder_activity, session_activity

SESSION = "19311184-276e-4c7a-9bee-c2605b06f1d1"
NOW = datetime(2026, 11, 3, 21, 0, tzinfo=UTC).timestamp()


def _turn(at: str, kind: str, **fields: object) -> dict:
    return {"type": kind, "timestamp": f"2026-11-03T{at}Z", **fields}


def _write(root: Path, *entries: dict) -> None:
    folder = root / "-home-adinb-trantor"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


def _assistant(at: str, *parts: dict) -> dict:
    return _turn(at, "assistant", message={"role": "assistant", "content": list(parts)})


def _user(at: str, *parts: dict) -> dict:
    return _turn(at, "user", message={"role": "user", "content": list(parts)})


def test_a_finished_turn_is_idle_since_its_end(tmp_path: Path) -> None:
    _write(
        tmp_path,
        _user("20:00:00.000", {"type": "text", "text": "go"}),
        _assistant("20:26:28.511", {"type": "text", "text": "done"}),
        _turn("20:26:32.710", "system", subtype="turn_duration"),
    )

    found = session_activity(tmp_path, SESSION, now=NOW)

    assert found == {"state": "idle", "last_turn_at": "2026-11-03T20:26:32.710Z", "idle_s": 2007}


@pytest.mark.parametrize(
    "last",
    [
        _assistant("20:30:00.000", {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
        _user("20:30:00.000", {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}),
        _user("20:30:00.000", {"type": "text", "text": "next prompt"}),
    ],
)
def test_a_turn_still_running_is_working(tmp_path: Path, last: dict) -> None:
    _write(tmp_path, _turn("20:26:32.710", "system", subtype="turn_duration"), last)

    found = session_activity(tmp_path, SESSION, now=NOW)

    assert found == {"state": "working", "last_turn_at": "2026-11-03T20:30:00.000Z"}


def test_an_interrupted_turn_is_idle(tmp_path: Path) -> None:
    _write(
        tmp_path,
        _assistant("20:30:00.000", {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
        _user("20:31:00.000", {"type": "text", "text": "[Request interrupted by user for tool use]"}),
    )

    found = session_activity(tmp_path, SESSION, now=NOW)

    assert found == {"state": "idle", "last_turn_at": "2026-11-03T20:31:00.000Z", "idle_s": 1740}


def test_entries_that_are_not_turns_do_not_decide_the_state(tmp_path: Path) -> None:
    _write(
        tmp_path,
        _assistant("20:30:00.000", {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
        _turn("20:30:01.000", "attachment"),
        _turn("20:30:02.000", "api-request"),
    )

    found = session_activity(tmp_path, SESSION, now=NOW)

    assert found == {"state": "working", "last_turn_at": "2026-11-03T20:30:00.000Z"}


def test_a_session_with_no_transcript_has_no_activity(tmp_path: Path) -> None:
    assert session_activity(tmp_path, SESSION, now=NOW) is None


def test_a_url_assignee_names_no_transcript(tmp_path: Path) -> None:
    _write(tmp_path, _turn("20:26:32.710", "system", subtype="turn_duration"))

    assert session_activity(tmp_path, "https://claude.ai/code/session_01DTu8", now=NOW) is None


@pytest.mark.parametrize("session", ["*", "19311184-*", "[1]9311184-276e-4c7a-9bee-c2605b06f1d1", "../x", "a?b"])
def test_a_session_id_with_glob_characters_names_no_transcript(tmp_path: Path, session: str) -> None:
    _write(tmp_path, _turn("20:26:32.710", "system", subtype="turn_duration"))

    assert session_activity(tmp_path, session, now=NOW) is None


def _register(root: Path, name: str, **fields: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.json").write_text(json.dumps(fields))


def test_a_local_assignee_reads_its_own_transcript(tmp_path: Path) -> None:
    _write(tmp_path / "projects", _turn("20:26:32.710", "system", subtype="turn_duration"))

    found = holder_activity(tmp_path / "projects", tmp_path / "sessions", SESSION, now=NOW)

    assert found["state"] == "idle"


def test_a_bridge_url_assignee_reads_the_transcript_of_the_session_it_names(tmp_path: Path) -> None:
    _write(tmp_path / "projects", _turn("20:26:32.710", "system", subtype="turn_duration"))
    _register(tmp_path / "sessions", "1", sessionId="other", bridgeSessionId="session_01OTHER")
    _register(tmp_path / "sessions", "2", sessionId=SESSION, bridgeSessionId="session_01DTu8XMjB")

    found = holder_activity(
        tmp_path / "projects", tmp_path / "sessions", "https://claude.ai/code/session_01DTu8XMjB", now=NOW
    )

    assert found["state"] == "idle"


def test_a_url_assignee_no_running_session_names_has_no_activity(tmp_path: Path) -> None:
    _write(tmp_path / "projects", _turn("20:26:32.710", "system", subtype="turn_duration"))

    assert (
        holder_activity(tmp_path / "projects", tmp_path / "sessions", "https://claude.ai/code/session_01GONE", now=NOW)
        is None
    )
