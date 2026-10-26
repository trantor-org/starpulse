"""`starpulse worker scheduler`: the sampler and loop run in their own process over the shared event log, `serve`'s
settings wake them, and a restart of the worker keeps what the log holds: the one start per task and a harness's pause."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starpulse._internal.config.config import load
from starpulse.event_log.event_log import EventLog
from starpulse.runtime import server
from starpulse.runtime.assembly import assemble, history_store
from starpulse.scheduler.adapters.loop import PAUSES_KEY
from starpulse.scheduler.adapters.remote import Remote
from starpulse.scheduler.bin.scheduler_worker import Scheduler
from starpulse.sessions.session_start import starter
from starpulse.tests.integration.scheduler.test_scheduler_served import IDLE_HOST, _start_service, _task, _until


@contextmanager
def _worker(base: Path, url: str) -> Iterator[tuple[Scheduler, Remote]]:
    """A worker over the native board and the event log in `base`, as `serve` (the `Remote`) sees it."""
    path = base / "starpulse.toml"
    path.write_text(f'session_start_url = "{url}"\n[board]\ninterval = 0.1\n')
    config = load(path)
    board, feed = assemble(config, base, None, ())
    log = EventLog(f"sqlite:///{base / 'events.sqlite'}")
    board.start(feed, "test-worker", log)
    worker = Scheduler(
        config,
        base,
        board,
        feed,
        log,
        history_store(config, base, feed.machines),
        probe=lambda: IDLE_HOST,
        trajectories_response=server.trajectories_response,
        cached=server._cached,
        starter=starter,
    )
    worker.start()
    try:
        yield worker, Remote(log, base / (config.scheduler.state_dir or ""))
    finally:
        worker.stop()


def _published(remote: Remote) -> bool:
    return "inFlight" in remote.served_status()


def test_the_worker_runs_the_loop_and_serves_switch_wakes_it(tmp_path: Path) -> None:
    _task(tmp_path, "To Do")
    with _start_service() as (url, asked), _worker(tmp_path, url) as (_, remote):
        _until(lambda: _published(remote), "the worker's first status")
        assert asked == []  # the switch is off

        remote.set_enabled(True)

        _until(lambda: asked, "the session start the switch woke")
        assert len(asked) == 1


def test_a_restarted_worker_does_not_start_a_task_it_already_started(tmp_path: Path) -> None:
    _task(tmp_path, "To Do")
    with _start_service() as (url, asked):
        with _worker(tmp_path, url) as (_, remote):
            remote.set_enabled(True)
            _until(lambda: asked, "the first start")

        with _worker(tmp_path, url) as (_, remote):  # the unit restarted: new process state over the same log
            _until(lambda: _published(remote), "the restarted worker's status")
            remote.set_quiet_hours(None)  # one more wake for the loop to look at the still-eligible task
            time.sleep(0.5)

            assert len(asked) == 1
            assert remote.served_status()["enabled"] is True


def test_a_restarted_worker_keeps_a_harness_paused(tmp_path: Path) -> None:
    _task(tmp_path, "To Do")
    until = time.time() + 3600
    with _start_service() as (url, asked):
        log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
        log.set_setting(PAUSES_KEY, {"claude": {"until": until, "reason": "usage limit"}})
        with _worker(tmp_path, url) as (_, remote):
            remote.set_enabled(True)
            _until(lambda: remote.served_status().get("pauses"), "the paused harness in the status")

            assert [pause["harness"] for pause in remote.served_status()["pauses"]] == ["claude"]
            assert asked == []
