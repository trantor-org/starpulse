"""Promoting a proposal renumbers it: the task takes the next task number, the proposal id stays an alias that still
resolves, and the board holds one row for it, not one per id."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.views.application.commands.moves import move_task

from tests.unit.board.test_native import native_root

LAN = "127.0.0.1"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "machines" / "proposed-board.yaml"
STATUSES = ["New", "Proposed", "Ready", "Waiting", "In Progress", "Done", "Archived"]


def _proposals(base: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[BoardFeed, Board, UpstreamBacklog]:
    """A native board, its feed and the one scanner that publishes its files, over `proposed-board.yaml`, numbering
    proposals `PROP-N` and tasks `TASK-N`."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    (base / "board.yaml").write_text(FIXTURE.read_text())
    (native_root(base) / "tasks").mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": STATUSES, "task_prefix": "TASK"})
    )
    built = board({"machine": "board.yaml", "proposal_prefix": "PROP"}, base)
    feed = BoardFeed(machines=built.machines(lambda name: name, ()), keys=built.keys, roles=built.roles)
    built.start(feed, "test", EventLog(f"sqlite:///{base / 'events.sqlite'}"))
    return feed, built, UpstreamBacklog(native_root(base), feed.put, retract=feed.retract)


def _create(built: Board, scanner: UpstreamBacklog, title: str, status: str) -> str:
    assert built.create is not None
    made = built.create(title, {"status": status})
    assert made.ok, made.output
    scanner.scan()
    return made.output


def _promote(feed: BoardFeed, built: Board, task: str) -> tuple[int, dict[str, Any]]:
    assert built.writer is not None
    return move_task(LAN, json.dumps({"task": task, "to": "ready"}).encode(), feed, built.writer)


def _states(feed: BoardFeed) -> dict[str, str]:
    return {agent["id"]: agent["state"] for agent in feed.open_tasks()}


def test_promoting_a_proposal_gives_it_the_next_task_number_and_keeps_the_proposal_id_as_an_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built, scanner = _proposals(tmp_path, monkeypatch)
    _create(built, scanner, "Real work", "Ready")
    proposal = _create(built, scanner, "Idea", "Proposed")

    status, body = _promote(feed, built, proposal)
    scanner.scan()

    assert (status, body.get("error")) == (200, None), body
    assert (status, proposal, body["task"]) == (200, "PROP-1", "TASK-2")
    assert _states(feed) == {"TASK-1": "ready", "TASK-2": "ready"}
    assert built.read("PROP-1") == built.read("TASK-2")
    assert built.read("TASK-2")["title"] == "Idea"
    assert feed.held("TASK-2") is not None
    assert feed.held("PROP-1") == feed.held("TASK-2")


def test_a_proposal_that_is_not_promoted_keeps_its_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built, scanner = _proposals(tmp_path, monkeypatch)
    proposal = _create(built, scanner, "Idea", "Proposed")

    assert _states(feed) == {proposal: "proposed"}


def test_a_proposal_that_holds_a_task_number_keeps_it_on_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built, scanner = _proposals(tmp_path, monkeypatch)
    legacy = _create(built, scanner, "Real work", "Ready")
    assert built.writer is not None
    # a task number held in the proposed lane, as before a migration
    assert built.writer(legacy, "Proposed", "operator").ok
    scanner.scan()

    status, body = _promote(feed, built, legacy)

    assert (status, body["task"], "was" in body) == (200, legacy, False)
