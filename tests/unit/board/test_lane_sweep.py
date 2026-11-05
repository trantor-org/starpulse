"""The lane sweep: a task whose file status and read-model state differ is re-read, and one still different on the next
pass is the board's alert (the `starpulse_board_lane_mismatch` gauge and an error line)."""

import logging
import threading

import pytest
from starpulse.board.adapters.lane_sweep import LaneSweep, mismatches
from starpulse.event_log.wake import StopEvent


class _Feed:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states

    def open_tasks(self) -> list[dict]:
        return [{"id": task, "state": state} for task, state in self.states.items()]


class _Board:
    def __init__(self, files: dict[str, str]) -> None:
        self.statuses, self.reconciled = files, []

    def read(self, task: str) -> dict | None:
        return {"status": self.statuses[task]} if task in self.statuses else None

    files = None

    def reconcile(self, task: str) -> bool:
        self.reconciled.append(task)
        return True


def test_mismatches_compare_the_files_lane_with_the_read_models_state() -> None:
    feed = _Feed({"TASK-1": "waiting", "TASK-2": "in_progress", "TASK-3": "ready", "TASK-4": "ready"})
    board = _Board({"TASK-1": "Ready", "TASK-2": "In Progress", "TASK-3": "Ready"})

    assert mismatches(feed.open_tasks(), board.read) == {"TASK-1": ("ready", "waiting")}


def test_a_mismatch_is_reconciled_and_alerts_only_when_the_next_pass_finds_it_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed = _Feed({"TASK-1": "waiting"})
    board = _Board({"TASK-1": "Ready"})
    sweep = LaneSweep(feed, board)

    sweep.sweep()
    assert board.reconciled == ["TASK-1"]
    assert "starpulse_board_lane_mismatch{" not in sweep.exposition()

    with caplog.at_level(logging.ERROR):
        sweep.sweep()
    assert 'starpulse_board_lane_mismatch{task="TASK-1",file="ready",board="waiting"} 1' in sweep.exposition()
    assert "TASK-1" in caplog.text


def test_a_mismatch_the_reconcile_cleared_raises_no_alert() -> None:
    feed = _Feed({"TASK-1": "waiting"})
    board = _Board({"TASK-1": "Ready"})
    sweep = LaneSweep(feed, board)

    sweep.sweep()
    feed.states["TASK-1"] = "ready"
    sweep.sweep()

    assert "starpulse_board_lane_mismatch{" not in sweep.exposition()
    assert sweep.exposition().endswith("\n")


def test_the_sweep_thread_ends_when_its_stop_event_is_set() -> None:
    stopped = StopEvent()
    LaneSweep(_Feed({}), _Board({})).start(stopped)
    thread = next(live for live in threading.enumerate() if live.name == "lane-sweep")

    stopped.set()
    thread.join(5)

    assert not thread.is_alive()


class _PlacingFeed(_Feed):
    def __init__(self, states: dict[str, str]) -> None:
        super().__init__(states)
        self.aliases: dict[str, str] = {}

    def alias(self, alias: str, task: str) -> None:
        self.aliases[alias] = task


class _PlacingBoard(_Board):
    def __init__(self, files: dict[str, str], listed: list[tuple[str, list[str]]]) -> None:
        super().__init__(files)
        self.listed = listed

    def files(self) -> list[tuple[str, list[str]]]:
        return self.listed


def test_a_file_the_read_model_lacks_is_reconciled_and_its_aliases_answer_its_id() -> None:
    feed = _PlacingFeed({"TASK-1": "ready"})
    board = _PlacingBoard({"TASK-1": "Ready", "PROP-2": "Proposed"}, [("TASK-1", []), ("PROP-2", ["TASK-9"])])

    LaneSweep(feed, board).sweep()

    assert board.reconciled == ["PROP-2"]
    assert feed.aliases == {"TASK-9": "PROP-2"}


def test_an_open_task_with_no_file_is_reconciled_when_a_second_pass_finds_it_still_absent() -> None:
    feed = _PlacingFeed({"TASK-1": "ready", "TASK-9": "proposed"})
    board = _PlacingBoard({"TASK-1": "Ready"}, [("TASK-1", [])])
    sweep = LaneSweep(feed, board)

    sweep.sweep()
    assert board.reconciled == []
    sweep.sweep()
    assert board.reconciled == ["TASK-9"]


def test_no_listed_files_leaves_every_open_task_alone() -> None:
    feed = _PlacingFeed({"TASK-1": "ready"})
    board = _PlacingBoard({}, [])
    sweep = LaneSweep(feed, board)

    sweep.sweep()
    sweep.sweep()

    assert board.reconciled == []
