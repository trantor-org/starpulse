"""GET /api/analytics/health against StarPulse's own store: the numbers on a fixture history, and what it refuses."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse.board_feed import BoardFeed
from starpulse.history import HistoryStore
from starpulse.tests.machines import MACHINES
from starpulse.adapter_kit import serve, url
from starpulse.tests.unit.test_analytics import NOW, ROWS, H


def _get(server: ThreadingHTTPServer, query: str = "") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/analytics/health{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, (task, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"l{i}", task, new, at)
    return store


@pytest.fixture
def server(tmp_path: Path, store: HistoryStore) -> Iterator[ThreadingHTTPServer]:
    with serve(tmp_path, BoardFeed(machines=MACHINES), history=store, clock=lambda: NOW) as server:
        yield server


def test_health_on_a_fixture_history_equals_the_hand_computed_values(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "?hours=48&stuck_hours=24")

    states = {state["id"]: state for state in body["states"]}
    assert status == 200
    assert (states["ready"]["visits"], states["ready"]["mean_s"], states["ready"]["max_s"]) == (3, 7 * H, 10 * H)
    assert (states["in_progress"]["visits"], states["in_progress"]["mean_s"]) == (4, 23.5 * H)
    assert {sid: s["wip"] for sid, s in states.items()} == {
        "to_do": 1,
        "ready": 1,
        "in_progress": 1,
        "review": 0,
        "done": 3,
    }
    assert body["throughput"] == {"count": 2, "per_day": 1.0}
    assert [(s["task"], s["dwell_s"], s["counted_to_now"]) for s in body["stuck"]] == [("C", 60 * H, True)]
    assert (body["now"], body["window_s"], body["stuck_after_s"], body["warnings"]) == (NOW, 48 * H, 24 * H, [])


def test_the_window_defaults_to_a_week_and_a_stay_to_a_day(server: ThreadingHTTPServer) -> None:
    _, body = _get(server)

    assert (body["window_s"], body["stuck_after_s"]) == (168 * H, 24 * H)


def test_a_recorded_gap_is_a_warning(server: ThreadingHTTPServer, store: HistoryStore) -> None:
    store.record_gap("machine:events", "5-0", "9-0", 3)

    (warning,) = _get(server)[1]["warnings"]

    assert (warning["kind"], warning["stream"], warning["lost"]) == ("gap", "machine:events", 3)


@pytest.mark.parametrize(
    "query", ["?hours=0", "?hours=-1", "?hours=soon", "?hours=nan", "?hours=inf", "?stuck_hours=0"]
)
def test_a_window_or_threshold_that_is_not_a_positive_number_is_refused(
    server: ThreadingHTTPServer, query: str
) -> None:
    status, body = _get(server, query)

    assert status == 400
    assert "positive number" in body["error"]


def test_a_history_that_cannot_list_lane_changes_is_not_implemented(tmp_path: Path) -> None:
    class Paths:
        def lane_path(self, task: str) -> list[dict]:
            return []

        def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
            return [], 0

    with serve(tmp_path, BoardFeed(machines=MACHINES), history=Paths()) as server:
        status, body = _get(server)

    assert (status, "does not keep" in body["error"]) == (501, True)
