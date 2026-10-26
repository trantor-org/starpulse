"""The one table of how far each reader got: an integer position, and the snapshot a reader rebuilds from."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel
from sqlalchemy import text
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.event_log import EventLog


class _Snapshot(BaseModel):
    SCHEMA_VERSION: ClassVar[int] = 2
    tasks: dict[str, int] = {}


class _NextSnapshot(_Snapshot):
    SCHEMA_VERSION: ClassVar[int] = 3


@pytest.fixture
def checkpoints(tmp_path: Path) -> Checkpoints:
    return EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}").checkpoints


def test_a_reader_with_no_checkpoint_loads_no_position_and_no_snapshot(checkpoints: Checkpoints) -> None:
    assert checkpoints.load("board:tasks", _Snapshot) == (None, None)


def test_a_saved_snapshot_loads_with_its_integer_position(checkpoints: Checkpoints) -> None:
    checkpoints.save("board:tasks", 7, _Snapshot(tasks={"TASK-1": 1}))

    assert checkpoints.load("board:tasks", _Snapshot) == (7, _Snapshot(tasks={"TASK-1": 1}))


def test_a_snapshot_of_another_schema_version_loads_its_position_and_no_snapshot(checkpoints: Checkpoints) -> None:
    checkpoints.save("board:tasks", 7, _Snapshot(tasks={"TASK-1": 1}))

    assert checkpoints.load("board:tasks", _NextSnapshot) == (7, None)


def test_a_snapshot_the_model_cannot_read_loads_its_position_and_no_snapshot(checkpoints: Checkpoints) -> None:
    checkpoints.save("board:tasks", 7, _Snapshot(tasks={"TASK-1": 1}))
    with checkpoints.engine.begin() as db:
        db.execute(text("UPDATE starpulse_checkpoints SET state = '{\"tasks\": 5}'"))

    assert checkpoints.load("board:tasks", _Snapshot) == (7, None)


def test_a_position_alone_is_saved_and_moved_forward_in_place(checkpoints: Checkpoints) -> None:
    checkpoints.save("forward:remote", 12)
    checkpoints.save("forward:remote", 40)

    assert checkpoints.load("forward:remote") == (40, None)


def test_a_save_inside_a_transaction_is_kept_or_dropped_with_it(checkpoints: Checkpoints) -> None:
    with pytest.raises(RuntimeError), checkpoints.engine.begin() as db:
        checkpoints.save("machine:events", 3, conn=db)
        raise RuntimeError("the entry was not recorded")

    assert checkpoints.load("machine:events") == (None, None)


def test_a_snapshot_saved_under_a_new_hash_removes_the_one_under_the_old_hash(checkpoints: Checkpoints) -> None:
    checkpoints.save("board:replica@aaaa", 4, _Snapshot())
    checkpoints.save("board:other@aaaa", 4, _Snapshot())

    checkpoints.save("board:replica@bbbb", 9, _Snapshot())

    assert [checkpoints.load(name)[0] for name in ("board:replica@aaaa", "board:replica@bbbb", "board:other@aaaa")] == [
        None,
        9,
        4,
    ]
