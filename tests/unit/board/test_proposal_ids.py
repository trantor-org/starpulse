"""A board with a `proposal_prefix` numbers each Proposed create from its own sequence, so a proposal consumes no task
number; without the setting a proposal takes the next task number as any create does."""

from pathlib import Path

import pytest
import yaml
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog

from tests.unit.board.test_native import native_root

FIXTURE = Path(__file__).parents[2] / "fixtures" / "machines" / "proposed-board.yaml"
STATUSES = ["New", "Proposed", "Ready", "Waiting", "In Progress", "Done", "Archived"]


def _board(base: Path, monkeypatch: pytest.MonkeyPatch, **settings: str) -> Board:
    """A native board over `proposed-board.yaml`, numbering tasks `TASK-N`, with `settings` added."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    (base / "board.yaml").write_text(FIXTURE.read_text())
    (native_root(base) / "tasks").mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": STATUSES, "task_prefix": "TASK"})
    )
    built = board({"machine": "board.yaml", **settings}, base)
    feed = BoardFeed(machines=built.machines(lambda name: name, ()), keys=built.keys, roles=built.roles)
    built.start(feed, "test", EventLog(f"sqlite:///{base / 'events.sqlite'}"))
    return built


def _create(built: Board, title: str, status: str) -> str:
    assert built.create is not None
    made = built.create(title, {"status": status})
    assert made.ok, made.output
    return made.output


def test_a_proposed_create_takes_a_proposal_id_and_consumes_no_task_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = _board(tmp_path, monkeypatch, proposal_prefix="PROP")

    ids = [
        _create(built, "First idea", "Proposed"),
        _create(built, "Real work", "Ready"),
        _create(built, "Second idea", "Proposed"),
        _create(built, "More work", "Ready"),
    ]

    assert ids == ["PROP-1", "TASK-1", "PROP-2", "TASK-2"]


def test_a_proposed_create_takes_a_task_number_without_a_proposal_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = _board(tmp_path, monkeypatch)

    assert [_create(built, "Idea", "Proposed"), _create(built, "Work", "Ready")] == ["TASK-1", "TASK-2"]
