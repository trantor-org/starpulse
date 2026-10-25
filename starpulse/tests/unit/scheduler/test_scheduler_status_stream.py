"""The feed publishes an `scheduler` event when status changes, so the page strip need not poll GET /api/scheduler."""

from __future__ import annotations

import json
import queue
from pathlib import Path

from starpulse._internal.config.scheduler import Scheduler
from starpulse.board.board_feed import BoardFeed
from starpulse._internal.scheduler.runtime import Runtime, build
from starpulse._internal.server.writes import scheduler
from starpulse.contracts.api.dto.scheduler import SchedulerStatus
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.harness import SESSION_MACHINES
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.tests.unit.server.test_scheduler_route import HOST, _feed


def _runtime(tmp_path: Path, feed: BoardFeed) -> Runtime:
    runtime = build(
        Scheduler(),
        tmp_path,
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: HOST,
        clock=lambda: 1000.0,
    )
    runtime.wire_status(feed.publish)
    return runtime


def _drain(changes: queue.Queue) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    while True:
        try:
            out.append(changes.get_nowait())
        except queue.Empty:
            return out


def test_a_sample_publishes_an_scheduler_event_matching_status(tmp_path: Path) -> None:
    feed = _feed()
    runtime = _runtime(tmp_path, feed)
    _, changes = feed.subscribe()
    _drain(changes)  # drop anything from subscribe's snapshot path

    runtime.sampler.sample()

    events = _drain(changes)
    assert [(kind, SchedulerStatus.model_validate(data).model_dump(by_alias=True, exclude_unset=True)) for kind, data in events if kind == "scheduler"] == [
        ("scheduler", SchedulerStatus.model_validate(runtime.status()).model_dump(by_alias=True, exclude_unset=True))
    ]


def test_a_put_publishes_an_scheduler_event_with_the_new_enabled(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    runtime = _runtime(tmp_path, feed)
    runtime.sampler.sample()
    _, changes = feed.subscribe()
    _drain(changes)

    status, body = scheduler("127.0.0.1", "PUT", json.dumps({"enabled": True}).encode(), runtime)

    assert status == 200
    assert body["enabled"] is True
    published = [data for kind, data in _drain(changes) if kind == "scheduler"]
    assert published and published[-1]["enabled"] is True


def test_a_get_serves_the_status_the_last_push_computed_without_computing_again(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, _feed())
    runtime.sampler.sample()
    pushed = runtime.status()
    runtime.status = lambda: (_ for _ in ()).throw(AssertionError("a GET recomputed the status"))  # type: ignore[method-assign]

    status, body = scheduler("127.0.0.1", "GET", b"", runtime)

    assert (status, body) == (200, pushed)
