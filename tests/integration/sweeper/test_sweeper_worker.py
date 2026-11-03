"""`starpulse worker sweeper` over a real SQLite store: one leased instance, a pass at start, metrics for `/metrics`."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.runtime import worker
from starpulse.sweeper.publish import metrics_of
from tests import fake_board

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


def _eventually(check: Callable[[], object]) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], EventLog]]:
    """`worker.main(["sweeper"])` on a config with `extra`, returning at once; yields the log the worker shares."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    held: list[threading.Event] = []
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))
    url = f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}"

    def start(extra: str = "") -> EventLog:
        config = tmp_path / "starpulse.toml"
        config.write_text(extra + BOARD)
        worker.main(["sweeper", "--config", str(config)])
        return EventLog(url)

    yield start
    for stop in held:
        stop.set()


def test_a_second_sweeper_against_the_same_store_exits_non_zero(run) -> None:
    run()

    with pytest.raises(SystemExit) as refused:
        run()

    assert refused.value.code != 0


def test_a_second_sweeper_prints_the_holder_to_stderr(run, capsys: pytest.CaptureFixture[str]) -> None:
    run()

    with pytest.raises(SystemExit):
        run()

    assert f"the sweeper lease is held by pid {os.getpid()}" in capsys.readouterr().err


def test_the_start_pass_samples_the_readers_journals_its_line_and_keeps_the_metrics(
    run, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="starpulse.sweeper")
    log = run()

    kept = metrics_of(log)
    assert _eventually(lambda: "starpulse_sweeper_passes_total 1" in kept())
    assert 'starpulse_sweeper_samples_total{kind="readers"}' in kept()
    assert any(r.getMessage().startswith("sweeper: pass 1: readers=") for r in caplog.records)
