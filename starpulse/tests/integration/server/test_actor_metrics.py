"""`GET /metrics` carries the task actor's counter and histogram when the actor runs."""

import threading
import urllib.request
from pathlib import Path

from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse.pulls.pulls import PullStore
from starpulse.pulls.task_actor import TaskActor
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.tests.task_actor_kit import MOVES, WAITS, WITHIN_S, until


def _metrics(server: object) -> str:
    with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
        return resp.read().decode()


def test_metrics_lists_the_task_actors_series_while_it_runs(tmp_path: Path) -> None:
    with serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), actor_metrics=lambda: "starpulse_task_actor_refusals_total 3\n"
    ) as server:
        body = _metrics(server)

    assert "starpulse_task_actor_refusals_total 3" in body.splitlines()


def test_metrics_serves_the_projection_and_handoff_histograms_of_a_real_actor(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    actor = TaskActor(feed, store, lambda *args, **kwargs: None, WAITS, MOVES)
    actor.timed_projection(lambda: None)()
    stop = threading.Event()
    actor.start(stop)
    assert actor.ready.wait(WITHIN_S)
    actor.store_changed()
    assert until(lambda: "starpulse_task_actor_handoff_seconds_count 1" in actor.exposition())
    stop.set()

    with serve(tmp_path, feed, actor_metrics=actor.exposition) as server:
        body = _metrics(server).splitlines()

    assert {"starpulse_task_actor_projection_seconds_count 1", "starpulse_task_actor_handoff_seconds_count 1"} <= set(
        body
    )


def test_metrics_has_no_actor_series_without_the_actor(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        body = _metrics(server)

    assert "starpulse_task_actor" not in body


def test_metrics_carries_the_unattributed_lane_counter_it_is_given(tmp_path: Path) -> None:
    with serve(
        tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), lane_metrics=lambda: "starpulse_board_lane_unattributed_total 2\n"
    ) as server:
        body = _metrics(server)

    assert "starpulse_board_lane_unattributed_total 2" in body.splitlines()
