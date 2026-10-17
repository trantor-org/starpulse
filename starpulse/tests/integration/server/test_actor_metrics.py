"""`GET /metrics` carries the task actor's counter and histogram when the actor runs."""

import urllib.request
from pathlib import Path

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse.tests.machines import MACHINES


def _metrics(server: object) -> str:
    with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
        return resp.read().decode()


def test_metrics_lists_the_task_actors_series_while_it_runs(tmp_path: Path) -> None:
    with serve(
        tmp_path, BoardFeed(machines=MACHINES), actor_metrics=lambda: "starpulse_task_actor_refusals_total 3\n"
    ) as server:
        body = _metrics(server)

    assert "starpulse_task_actor_refusals_total 3" in body.splitlines()


def test_metrics_has_no_actor_series_without_the_actor(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES)) as server:
        body = _metrics(server)

    assert "starpulse_task_actor" not in body


def test_metrics_carries_the_unattributed_lane_counter_it_is_given(tmp_path: Path) -> None:
    with serve(
        tmp_path, BoardFeed(machines=MACHINES), lane_metrics=lambda: "starpulse_board_lane_unattributed_total 2\n"
    ) as server:
        body = _metrics(server)

    assert "starpulse_board_lane_unattributed_total 2" in body.splitlines()
