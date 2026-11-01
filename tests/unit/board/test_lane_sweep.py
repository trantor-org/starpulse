"""The lane sweep: a task whose file status and read-model state differ is re-read, and one still different on the next
pass is the board's alert (the `starpulse_board_lane_mismatch` gauge and an error line)."""

import logging
import threading

import pytest
from starpulse.board.adapters.lane_sweep import LaneSweep, mismatches


class _Feed:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states

    def open_tasks(self) -> list[dict]:
        return [{"id": task, "state": state} for task, state in self.states.items()]


class _Board:
    def __init__(self, files: dict[str, str]) -> None:
        self.files, self.reconciled = files, []

    def read(self, task: str) -> dict | None:
        return {"status": self.files[task]} if task in self.files else None

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
    stopped = threading.Event()
    LaneSweep(_Feed({}), _Board({})).start(stopped)
    thread = next(live for live in threading.enumerate() if live.name == "lane-sweep")

    stopped.set()
    thread.join(5)

    assert not thread.is_alive()
