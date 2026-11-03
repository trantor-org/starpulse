"""`task show` and `board` give an In Progress task's holder a `session_activity`: working, idle or unknown."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from starpulse.cli.agent_tasks import with_activity

SESSION = "19311184-276e-4c7a-9bee-c2605b06f1d1"
NOW = datetime(2026, 11, 3, 21, 0, tzinfo=UTC).timestamp()


def _transcript(root: Path) -> None:
    folder = root / "-home-adinb-trantor"
    folder.mkdir(parents=True)
    entry = {"type": "system", "subtype": "turn_duration", "timestamp": "2026-11-03T20:26:32.710Z"}
    (folder / f"{SESSION}.jsonl").write_text(json.dumps(entry) + "\n")


def _view(lane: str, assignee: str) -> dict:
    return {"id": "TASK-1", "lane": lane, "assignee": assignee}


def test_an_in_progress_task_shows_its_holders_activity(tmp_path: Path) -> None:
    _transcript(tmp_path / "projects")

    shown = with_activity(
        _view("in_progress", SESSION), "in_progress", tmp_path / "projects", tmp_path / "sessions", NOW
    )

    assert shown["session_activity"] == {"state": "idle", "last_turn_at": "2026-11-03T20:26:32.710Z", "idle_s": 2007}


def test_a_holder_that_is_not_a_running_session_is_unknown(tmp_path: Path) -> None:
    shown = with_activity(
        _view("in_progress", "https://claude.ai/code/session_01GONE"), "in_progress", tmp_path, tmp_path, NOW
    )

    assert shown["session_activity"] == {"state": "unknown"}


def test_a_task_in_another_lane_or_with_no_holder_has_no_session_activity(tmp_path: Path) -> None:
    for view in (_view("review", SESSION), _view("in_progress", "")):
        assert "session_activity" not in with_activity(view, "in_progress", tmp_path, tmp_path, NOW)


def test_the_working_lane_is_the_one_the_machine_names(tmp_path: Path) -> None:
    _transcript(tmp_path / "projects")

    shown = with_activity(_view("doing", SESSION), "doing", tmp_path / "projects", tmp_path / "sessions", NOW)
    other = with_activity(_view("in_progress", SESSION), "doing", tmp_path / "projects", tmp_path / "sessions", NOW)

    assert shown["session_activity"]["state"] == "idle"
    assert "session_activity" not in other
