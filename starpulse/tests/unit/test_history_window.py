"""The shared history window: the declared `--hours`, the override Admin writes, and the endpoint that serves both."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from starpulse.api.adapter_kit import serve, url
from starpulse.api.server import history_window
from starpulse.projections.board_feed import BoardFeed
from starpulse.projections.machine_tasks import MachineTasks
from starpulse.settings.history_window import HistoryWindow
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.test_machine_tasks import _entry
from starpulse.tests.unit.test_server import _ip

REFUSED = "history window must be between 1 and 72 hours; got {}"


def _window(tmp_path: Path, hours: float = 6) -> tuple[BoardFeed, HistoryWindow]:
    feed = BoardFeed(hours * 3600, machines=MACHINES)
    return feed, HistoryWindow(feed, hours, tmp_path / "starpulse-settings.json")


def _drawn(feed: BoardFeed) -> list[str]:
    flow = next(f for f in feed.snapshot()["flows"] if f["name"] == "in-progress")
    return sorted(a["id"] for a in flow["agents"])


def _put(window: HistoryWindow, body: object) -> tuple[int, dict]:
    return history_window("127.0.0.1", "PUT", json.dumps(body).encode(), window)


def test_with_no_override_the_declared_hours_are_the_window(tmp_path: Path) -> None:
    _, window = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "GET", b"", window) == (200, {"hours": 6, "default": 6, "overridden": False})


def test_a_valid_put_persists_and_changes_the_window_the_feed_draws_with(tmp_path: Path) -> None:
    feed, window = _window(tmp_path, 6)
    tasks = MachineTasks(feed)
    now = time.time()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-1", at=now - 10 * 3600))
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-2", at=now - 60))
    assert _drawn(feed) == ["PROJ-2"]

    status, body = _put(window, {"hours": 24})

    assert (status, body) == (200, {"hours": 24, "default": 6, "overridden": True})
    assert _drawn(feed) == ["PROJ-1", "PROJ-2"]
    assert json.loads((tmp_path / "starpulse-settings.json").read_text()) == {"history_hours": 24}


def test_the_window_is_exactly_the_hours_set_counted_in_seconds(tmp_path: Path) -> None:
    feed, window = _window(tmp_path, 6)
    tasks = MachineTasks(feed)
    now = time.time()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-1", at=now - 24 * 3600 - 10))
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-2", at=now - 24 * 3600 + 10))

    _put(window, {"hours": 24})

    assert _drawn(feed) == ["PROJ-2"]


def test_a_window_change_reaches_a_page_that_is_already_connected(tmp_path: Path) -> None:
    feed, window = _window(tmp_path, 6)
    _, changes = feed.subscribe()

    _put(window, {"hours": 24})

    kind, snapshot = changes.get_nowait()
    assert kind == "snapshot"
    assert snapshot["flows"][0]["name"] == "board"


@pytest.mark.parametrize("hours", [0, 73, -1, 0.5, 72.5, "6", None, True, [24], float("nan"), float("inf")])
def test_an_hours_outside_one_to_seventy_two_or_not_a_number_is_refused_and_the_window_stays(
    tmp_path: Path, hours: object
) -> None:
    _, window = _window(tmp_path, 6)

    status, body = _put(window, {"hours": hours})

    assert (status, body) == (400, {"error": REFUSED.format(hours)})
    assert history_window("127.0.0.1", "GET", b"", window)[1]["hours"] == 6
    assert not (tmp_path / "starpulse-settings.json").exists()


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

    assert (status, body) == (400, {"error": 'a history window needs {"hours": N}'})


def test_the_override_survives_a_restart_and_reset_returns_to_the_declared_hours(tmp_path: Path) -> None:
    _, first = _window(tmp_path, 6)
    _put(first, {"hours": 24})

    _, restarted = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "GET", b"", restarted) == (200, {"hours": 24, "default": 6, "overridden": True})
    assert history_window("127.0.0.1", "DELETE", b"", restarted) == (
        200,
        {"hours": 6, "default": 6, "overridden": False},
    )
    assert not (tmp_path / "starpulse-settings.json").exists()
    assert history_window("127.0.0.1", "GET", b"", _window(tmp_path, 6)[1])[1]["overridden"] is False


def test_a_restarted_feed_draws_with_the_override_not_the_declared_hours(tmp_path: Path) -> None:
    _, first = _window(tmp_path, 6)
    _put(first, {"hours": 24})
    feed, _ = _window(tmp_path, 6)
    now = time.time()
    MachineTasks(feed).handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-1", at=now - 10 * 3600))

    assert _drawn(feed) == ["PROJ-1"]


def test_resetting_with_no_override_is_a_no_op(tmp_path: Path) -> None:
    _, window = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "DELETE", b"", window) == (200, {"hours": 6, "default": 6, "overridden": False})


@pytest.mark.parametrize("text", ["", "{", "[]", '{"history_hours": 500}', '{"history_hours": "x"}', '{"other": 1}'])
def test_a_settings_file_that_cannot_be_read_as_a_valid_window_leaves_the_declared_hours(
    tmp_path: Path, text: str
) -> None:
    (tmp_path / "starpulse-settings.json").write_text(text)

    _, window = _window(tmp_path, 6)

    assert history_window("127.0.0.1", "GET", b"", window)[1] == {"hours": 6, "default": 6, "overridden": False}


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
    feed, window = _window(tmp_path, 6)

    def call(method: str, body: bytes | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            url(server, "/api/history-window"), data=body, headers={"Content-Type": "application/json"}, method=method
        )
        try:
            with urllib.request.urlopen(request) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as err:
            return err.code, json.load(err)

    with serve(tmp_path, feed=feed, window=window) as server:
        assert call("GET") == (200, {"hours": 6, "default": 6, "overridden": False})
        assert call("PUT", b'{"hours": 24}') == (200, {"hours": 24, "default": 6, "overridden": True})
        assert call("PUT", b'{"hours": 200}') == (400, {"error": REFUSED.format(200)})
        assert call("GET")[1]["hours"] == 24
        assert call("DELETE") == (200, {"hours": 6, "default": 6, "overridden": False})


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_a_put_or_delete_to_any_other_path_is_a_404_and_leaves_the_window(tmp_path: Path, method: str) -> None:
    feed, window = _window(tmp_path, 6)

    with serve(tmp_path, feed=feed, window=window) as server:
        request = urllib.request.Request(url(server, "/api/move-it"), data=b'{"hours": 24}', method=method)
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)

    assert refused.value.code == 404
    assert window.state()["overridden"] is False


def test_a_history_with_lane_rows_and_no_gaps_can_size_suns_but_not_answer_health() -> None:
    from starpulse.store.history import HealthHistory, LaneHistory

    class LanesOnly:
        def lane_path(self, task: str) -> list[dict]:
            return []

        def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
            return [], 0

        def lane_rows(self, since: float | None = None) -> list[tuple[str, float, str | None, str]]:
            return []

    assert isinstance(LanesOnly(), LaneHistory)
    assert not isinstance(LanesOnly(), HealthHistory)
    assert not isinstance(object(), LaneHistory)
