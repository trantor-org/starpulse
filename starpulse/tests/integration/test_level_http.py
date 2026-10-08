"""GET /api/level against StarPulse's own store: the numbers on a fixture history equal the Backlog flow metric
definitions' (and the Board health's where the two count the same), a window past the history is refused, and a server
with no level has none to serve."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse.api.adapter_kit import serve, url
from starpulse.domain.level import Level, Orbit, Terminal
from starpulse.projections.analytics import board_health
from starpulse.projections.board_feed import BoardFeed
from starpulse.store.history import HistoryStore
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.test_analytics import BOARD, NOW, ROWS, H

LEVEL = Level(
    "board",
    "done",
    (Terminal("done", "goal"),),
    gates=("review",),
    orbit=Orbit("working", ("in_progress", "review")),
)


def _get(server: ThreadingHTTPServer, query: str = "", path: str = "/api/level") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"{path}{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, (task, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"{'a' if task in 'AB' else 'b'}/{i}", task, new, at)
    return store


@pytest.fixture
def server(tmp_path: Path, store: HistoryStore) -> Iterator[ThreadingHTTPServer]:
    with serve(tmp_path, BoardFeed(machines=MACHINES), history=store, clock=lambda: NOW, level=LEVEL) as server:
        yield server


def test_wip_throughput_and_aging_on_a_fixture_history_equal_the_definitions(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "?hours=48")

    assert status == 200
    assert body["wip"] == {"count": 1, "states": {"in_progress": 1}}  # C, working since 40h
    assert body["throughput"] == {"count": 2, "per_day": 1.0}  # A at 90h and B at 95h; F finished before the window
    assert body["aging"]["threshold_s"] == 25 * H  # cycles A 20h, B 25h, F 10h: nearest rank 0.85 * 3 is the third
    assert body["aging"]["runs"] == [
        {"source": "b", "task": "C", "state": "in_progress", "age_s": 60 * H, "over": True}
    ]
    assert (body["now"], body["window_s"], body["history_s"]) == (NOW, 48 * H, 90 * H)


def test_the_numbers_both_count_agree_with_the_board_health_of_the_same_history(server: ThreadingHTTPServer) -> None:
    health = board_health(BOARD, ROWS, [], now=NOW, window_s=48 * H, stuck_s=24 * H)
    wip = {state["id"]: state["wip"] for state in health["states"]}

    _, body = _get(server, "?hours=48")

    assert body["throughput"] == health["throughput"]
    assert body["wip"]["states"] == {
        "in_progress": wip["in_progress"]
    }  # health also counts its initial and ready lanes
    assert wip["review"] == 0


def test_time_in_state_clips_each_stay_to_the_window(server: ThreadingHTTPServer) -> None:
    _, body = _get(server, "?hours=48")

    states = {state["id"]: state for state in body["time_in_state"]}
    # A 10h, B 15h and 9h, C 48h of its 60h; F left before the window opened
    assert (states["in_progress"]["visits"], states["in_progress"]["task_s"]) == (4, 82 * H)


def test_each_source_carries_shares_that_sum_to_one(server: ThreadingHTTPServer) -> None:
    _, body = _get(server, "?hours=48")

    by_source = {source["id"]: source for source in body["sources"]}
    assert set(by_source) == {"a", "b"}
    assert by_source["a"]["terminal_share"] == {"done": 1.0}  # A and B ended in done
    assert sum(by_source["a"]["time_share"].values()) == pytest.approx(1.0)
    assert sum(by_source["b"]["time_share"].values()) == pytest.approx(1.0)


def test_a_window_longer_than_the_history_is_refused_with_the_history_length(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "?hours=91")

    assert status == 400
    assert body["history_s"] == 90 * H
    assert "90 hours" in body["error"]


def test_the_default_window_a_short_history_cannot_cover_is_refused_not_padded(server: ThreadingHTTPServer) -> None:
    status, body = _get(server)

    assert (status, body["history_s"]) == (400, 90 * H)


@pytest.mark.parametrize("query", ["?hours=0", "?hours=-1", "?hours=soon", "?hours=nan", "?hours=inf"])
def test_a_window_that_is_not_a_positive_number_is_refused(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _get(server, query)

    assert status == 400
    assert "positive number" in body["error"]


def test_a_server_with_no_level_has_none_to_serve(tmp_path: Path, store: HistoryStore) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES), history=store, clock=lambda: NOW) as server:
        status, body = _get(server, "?hours=48")

    assert status == 404
    assert "no level" in body["error"]


def test_a_history_that_cannot_list_runs_is_not_implemented(tmp_path: Path) -> None:
    class Paths:
        def lane_path(self, task: str) -> list[dict]:
            return []

        def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
            return [], 0

    with serve(tmp_path, BoardFeed(machines=MACHINES), history=Paths(), level=LEVEL) as server:
        status, body = _get(server, "?hours=48")

    assert (status, "does not keep" in body["error"]) == (501, True)


def _trajectories(server: ThreadingHTTPServer, query: str = "") -> tuple[int, dict]:
    return _get(server, query, "/api/level/trajectories")


def test_trajectories_cover_the_runs_that_ended_in_the_window(server: ThreadingHTTPServer) -> None:
    status, body = _trajectories(server, "?hours=48")

    assert status == 200
    assert (body["ended"], body["window_s"], body["history_s"]) == (2, 48 * H, 90 * H)  # A at 90h, B at 95h; F at 40h
    assert [(run["task"], run["path"]) for run in body["runs"]] == [
        ("A", ["to_do", "ready", "in_progress", "review", "done"]),
        ("B", ["ready", "in_progress", "review", "in_progress", "done"]),
    ]
    assert body["norm"]["count"] == 1
    assert body["chain"]["in_progress"]["p_goal"] == pytest.approx(1.0)  # every ended run reached the goal


def test_a_run_that_detoured_through_the_gate_leaves_it_bypassable_with_that_runs_own_path(
    server: ThreadingHTTPServer,
) -> None:
    _, body = _trajectories(server, "?hours=48")

    assert body["gates"] == [
        {
            "gate": "review",
            "runs": 2,
            "crossed": 2,
            "mandatory": 1,  # A; B went back to in progress and on to done
            "bypassed": 1,
            "bypassable": True,
            "witness": {"task": "B", "path": ["ready", "in_progress", "done"]},
        }
    ]


def test_trajectories_refuse_a_window_longer_than_the_history_with_its_length(server: ThreadingHTTPServer) -> None:
    status, body = _trajectories(server, "?hours=91")

    assert (status, body["history_s"], "90 hours" in body["error"]) == (400, 90 * H, True)


@pytest.mark.parametrize("query", ["?hours=0", "?hours=soon"])
def test_trajectories_refuse_a_window_that_is_not_a_positive_number(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _trajectories(server, query)

    assert (status, "positive number" in body["error"]) == (400, True)


def test_a_server_with_no_level_has_no_trajectories(tmp_path: Path, store: HistoryStore) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES), history=store, clock=lambda: NOW) as server:
        status, body = _trajectories(server, "?hours=48")

    assert (status, "no level" in body["error"]) == (404, True)


def test_a_history_that_cannot_list_runs_cannot_report_trajectories(tmp_path: Path) -> None:
    class Paths:
        def lane_path(self, task: str) -> list[dict]:
            return []

        def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
            return [], 0

    with serve(tmp_path, BoardFeed(machines=MACHINES), history=Paths(), level=LEVEL) as server:
        status, body = _trajectories(server, "?hours=48")

    assert (status, "does not keep" in body["error"]) == (501, True)
