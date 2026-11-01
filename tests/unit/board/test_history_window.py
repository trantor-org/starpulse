"""The shared history window: the declared `--hours`, the override Admin writes, and the endpoint that serves both."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import MachineEvent
from starpulse.event_log.event_log import EventLog
from starpulse.runtime.adapter_kit import serve, url
from starpulse.views.application.commands.settings import history_window

from tests.machine_feed import MachineFeed
from tests.machines import MACHINES
from tests.unit.runtime.test_server import _ip

REFUSED = "history window must be between 1 and 72 hours; got {}"


def _log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


def _window(tmp_path: Path, hours: float = 6) -> tuple[MachineFeed, HistoryWindow]:
    machine = MachineFeed(tmp_path / "events.sqlite", MACHINES, window_s=hours * 3600)
    return machine, HistoryWindow(machine.feed, hours, _log(tmp_path))


def _task(machine: MachineFeed, task: str, at: float) -> None:
    machine.put(MachineEvent(machine="in-progress", event="WORKTREE_READY", task=task, time=at))


def _drawn(feed: BoardFeed) -> list[str]:
    flow = next(f for f in feed.snapshot()["flows"] if f["name"] == "in-progress")
    return sorted(a["id"] for a in flow["agents"])


def _put(window: HistoryWindow, body: object) -> tuple[int, dict]:
    return history_window("127.0.0.1", "PUT", json.dumps(body).encode(), window)


def test_with_no_override_the_declared_hours_are_the_window(tmp_path: Path) -> None:
    _, window = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "GET", b"", window) == (200, {"hours": 6, "default": 6, "overridden": False})


def test_a_valid_put_persists_and_changes_the_window_the_feed_draws_with(tmp_path: Path) -> None:
    machine, window = _window(tmp_path, 6)
    now = time.time()
    _task(machine, "PROJ-1", now - 10 * 3600)
    _task(machine, "PROJ-2", now - 60)
    assert _drawn(machine.feed) == ["PROJ-2"]

    status, body = _put(window, {"hours": 24})

    assert (status, body) == (200, {"hours": 24, "default": 6, "overridden": True})
    assert _drawn(machine.feed) == ["PROJ-1", "PROJ-2"]
    assert _log(tmp_path).setting("history.hours") == 24
    assert not (tmp_path / "starpulse-settings.json").exists()


def test_the_window_is_exactly_the_hours_set_counted_in_seconds(tmp_path: Path) -> None:
    machine, window = _window(tmp_path, 6)
    now = time.time()
    _task(machine, "PROJ-1", now - 24 * 3600 - 10)
    _task(machine, "PROJ-2", now - 24 * 3600 + 10)

    _put(window, {"hours": 24})

    assert _drawn(machine.feed) == ["PROJ-2"]


def test_a_window_change_reaches_a_page_that_is_already_connected(tmp_path: Path) -> None:
    machine, window = _window(tmp_path, 6)
    _, changes = machine.feed.subscribe()

    _put(window, {"hours": 24})

    kind, snapshot = changes.get_nowait()
    assert kind == "snapshot"
    assert snapshot["flows"][0]["name"] == "board"


@pytest.mark.parametrize("hours", [0, 73, -1, 0.5, 72.5, float("nan"), float("inf")])
def test_an_hours_outside_one_to_seventy_two_is_refused_and_the_window_stays(tmp_path: Path, hours: object) -> None:
    _, window = _window(tmp_path, 6)

    status, body = _put(window, {"hours": hours})

    assert (status, body) == (400, {"error": REFUSED.format(float(hours))})
    assert history_window("127.0.0.1", "GET", b"", window)[1]["hours"] == 6
    assert _log(tmp_path).setting("history.hours") is None


@pytest.mark.parametrize("hours", ["6", None, True, [24]])
def test_an_hours_that_is_not_a_number_is_a_400_and_the_window_stays(tmp_path: Path, hours: object) -> None:
    _, window = _window(tmp_path, 6)

    status, body = _put(window, {"hours": hours})

    assert (status, body) == (400, {"error": "invalid request: hours: Input should be a valid number"})
    assert history_window("127.0.0.1", "GET", b"", window)[1]["hours"] == 6
    assert _log(tmp_path).setting("history.hours") is None


@pytest.mark.parametrize("hours", [1, 72, 1.5])
def test_the_ends_of_the_range_are_accepted(tmp_path: Path, hours: float) -> None:
    _, window = _window(tmp_path, 6)

    assert _put(window, {"hours": hours})[0] == 200


@pytest.mark.parametrize(
    "raw", [b"", b"{", b"[]", b'{"hrs": 24}', b'"24"'], ids=["empty", "bad-json", "list", "no-hours", "string"]
)
def test_a_body_that_does_not_name_the_hours_is_a_bad_request(tmp_path: Path, raw: bytes) -> None:
    _, window = _window(tmp_path, 6)

    status, body = history_window("127.0.0.1", "PUT", raw, window)

    assert status == 400 and body["error"].startswith("invalid request: ")


def test_the_override_survives_a_restart_and_reset_returns_to_the_declared_hours(tmp_path: Path) -> None:
    _, first = _window(tmp_path, 6)
    _put(first, {"hours": 24})

    _, restarted = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "GET", b"", restarted) == (200, {"hours": 24, "default": 6, "overridden": True})
    assert history_window("127.0.0.1", "DELETE", b"", restarted) == (
        200,
        {"hours": 6, "default": 6, "overridden": False},
    )
    assert _log(tmp_path).setting("history.hours") is None
    assert history_window("127.0.0.1", "GET", b"", _window(tmp_path, 6)[1])[1]["overridden"] is False


def test_a_restarted_feed_draws_with_the_override_not_the_declared_hours(tmp_path: Path) -> None:
    _, first = _window(tmp_path, 6)
    _put(first, {"hours": 24})
    machine, _ = _window(tmp_path, 6)
    _task(machine, "PROJ-1", time.time() - 10 * 3600)

    assert _drawn(machine.feed) == ["PROJ-1"]


def test_resetting_with_no_override_is_a_no_op(tmp_path: Path) -> None:
    _, window = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "DELETE", b"", window) == (200, {"hours": 6, "default": 6, "overridden": False})


#: A public (RFC 5737) address, the first one past 172.16/12, and a documentation IPv6 address.
@pytest.mark.parametrize("source", ["203.0.113.5", _ip(172, 32, 0, 1), "2001:db8::1"])
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_a_source_outside_loopback_and_rfc_1918_is_refused_and_changes_nothing(
    tmp_path: Path, source: str, method: str
) -> None:
    _, window = _window(tmp_path, 6)

    status, body = history_window(source, method, b'{"hours": 24}', window)

    assert status == 403
    assert body == {"error": "The history window answers only loopback and private network (RFC 1918) browsers"}
    assert history_window("127.0.0.1", "GET", b"", window)[1]["hours"] == 6


def test_the_server_answers_get_put_and_delete_on_the_history_window_route(tmp_path: Path) -> None:
    machine, window = _window(tmp_path, 6)

    def call(method: str, body: bytes | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            url(server, "/api/history-window"), data=body, headers={"Content-Type": "application/json"}, method=method
        )
        try:
            with urllib.request.urlopen(request) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as err:
            return err.code, json.load(err)

    with serve(tmp_path, feed=machine.feed, window=window) as server:
        assert call("GET") == (200, {"hours": 6, "default": 6, "overridden": False})
        assert call("PUT", b'{"hours": 24}') == (200, {"hours": 24, "default": 6, "overridden": True})
        assert call("PUT", b'{"hours": 200}') == (400, {"error": REFUSED.format(200.0)})
        assert call("GET")[1]["hours"] == 24
        assert call("DELETE") == (200, {"hours": 6, "default": 6, "overridden": False})


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_a_put_or_delete_to_any_other_path_is_a_404_and_leaves_the_window(tmp_path: Path, method: str) -> None:
    machine, window = _window(tmp_path, 6)

    with serve(tmp_path, feed=machine.feed, window=window) as server:
        request = urllib.request.Request(url(server, "/api/move-it"), data=b'{"hours": 24}', method=method)
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)

    assert refused.value.code == 404
    assert window.state()["overridden"] is False


def test_a_history_with_lane_rows_and_no_gaps_can_feed_the_ledger_but_not_answer_health() -> None:
    from starpulse.flow_metrics.adapters.outbound.history import HealthHistory, LaneHistory

    class LanesOnly:
        def lane_path(self, task: str) -> list[dict]:
            return []

        def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
            return [], 0

        def task_events(self, task: str, since: float, now: float) -> list[dict]:
            return []

        def lane_rows(self, since: float | None = None) -> list[tuple[str, float, str | None, str]]:
            return []

    assert isinstance(LanesOnly(), LaneHistory)
    assert not isinstance(LanesOnly(), HealthHistory)
    assert not isinstance(object(), LaneHistory)
