"""`/api/scheduler`: the toggle and what the capacity strip draws; a write answers only the private network."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.machine_tasks import MachineTasks
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import BoardTask, MachineEvent
from starpulse.contracts.api.dto.scheduler import SchedulerStatus
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.harness import SESSION_MACHINES
from starpulse.runtime.adapter_kit import serve, url
from starpulse.scheduler.adapters.runtime import Runtime, build
from starpulse.scheduler.model.config import Scheduler
from starpulse.scheduler.model.sampler import Crossing
from starpulse.views.page_server import PageServer
from starpulse.views.writes import scheduler

from tests.machines import MACHINES, ROLES

HOST = {"cpu": 35.0, "memory": 60.0}


def _feed() -> BoardFeed:
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    for task, lane, labels in (("T-1", "review", ["size-5"]), ("T-2", "review", []), ("T-3", "to_do", ["size-8"])):
        feed.put(BoardTask(id=task, team="demo", title=task, lane=lane, labels=labels))
    started = MachineEvent(machine="harness", event="SESSION_STARTED", task="T-3", time=time.time())
    MachineTasks(feed).put(started)  # the path a harness adapter's event takes
    return feed


def _runtime(tmp_path: Path, feed: BoardFeed | None = None, crossings: list[Crossing] | None = None) -> Runtime:
    return build(
        Scheduler(),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed or _feed(),
        probe=lambda: HOST,
        on_crossing=(crossings if crossings is not None else []).append,
        clock=lambda: 1000.0,
    )


def _put(runtime: Runtime, body: object, source: str = "127.0.0.1") -> tuple[int, dict]:
    return scheduler(source, "PUT", json.dumps(body).encode(), runtime)


def test_a_get_reports_every_dimensions_use_and_limit_and_that_the_scheduler_is_off(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.sampler.sample()

    status, body = scheduler("127.0.0.1", "GET", b"", runtime)

    assert status == 200
    assert body == {
        "enabled": False,
        "harness": "claude",
        "quietHours": None,
        "sampledAt": 1000.0,
        "dimensions": [
            {"name": "cpu", "use": 35.0, "limit": 80},
            {"name": "memory", "use": 60.0, "limit": 80},
            {"name": "sessions", "use": 1, "limit": 2},  # T-3's harness session is active
            {"name": "review", "use": 8, "limit": 20},  # size-5 plus the unsized task's default 3
        ],
    }


def test_a_get_before_the_first_sample_has_no_readings(tmp_path: Path) -> None:
    assert scheduler("127.0.0.1", "GET", b"", _runtime(tmp_path)) == (
        200,
        {"enabled": False, "harness": "claude", "quietHours": None, "sampledAt": None, "dimensions": []},
    )


def test_a_get_answers_any_address(tmp_path: Path) -> None:
    assert scheduler("203.0.113.9", "GET", b"", _runtime(tmp_path))[0] == 200


def test_a_put_turns_the_scheduler_on_and_off_and_a_restart_keeps_it(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    assert _put(runtime, {"enabled": True})[1]["enabled"] is True
    assert scheduler("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["enabled"] is True  # a restarted server

    assert _put(runtime, {"enabled": False})[1]["enabled"] is False
    assert scheduler("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["enabled"] is False


@pytest.mark.parametrize("source", ["127.0.0.1", "::1", "10.1.2.3", "172.16.0.9", "172.31.255.1", "192.168.1.20"])
def test_a_put_from_loopback_or_rfc_1918_is_taken(tmp_path: Path, source: str) -> None:
    assert _put(_runtime(tmp_path), {"enabled": True}, source)[0] == 200


@pytest.mark.parametrize("source", ["8.8.8.8", "203.0.113.9", "172.32.0.1", "11.0.0.1", "2001:db8::1"])
def test_a_put_from_outside_the_private_network_is_refused_and_changes_nothing(tmp_path: Path, source: str) -> None:
    runtime = _runtime(tmp_path)

    status, body = _put(runtime, {"enabled": True}, source)

    assert status == 403 and "RFC 1918" in body["error"]
    assert runtime.toggle.get() is False


@pytest.mark.parametrize("body", [{}, {"enabled": "yes"}, {"enabled": 1}])
def test_a_put_that_is_not_a_boolean_is_a_400_and_changes_nothing(tmp_path: Path, body: object) -> None:
    runtime = _runtime(tmp_path)

    status, answer = _put(runtime, body)

    assert status == 400 and "enabled" in answer["error"]
    assert runtime.toggle.get() is False


def test_a_put_that_is_not_json_is_a_400(tmp_path: Path) -> None:
    assert scheduler("127.0.0.1", "PUT", b"{", _runtime(tmp_path))[0] == 400


def test_an_instance_without_a_runtime_has_no_scheduler_route(tmp_path: Path) -> None:
    assert scheduler("127.0.0.1", "GET", b"", None)[0] == 404


def _looping(tmp_path: Path) -> Runtime:
    """A runtime with a dispatch loop over one Ready task and a quiet host, already sampled."""
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    feed.put(
        BoardTask(
            id="T-4", team="demo", title="Serve it", lane="ready", labels=["size-1"], profile="@agent-standard-high"
        )
    )
    runtime = build(
        Scheduler(lane="ready"),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: {"cpu": 5.0, "memory": 5.0},
        clock=lambda: 1000.0,
        start=lambda task, **_: f"https://claude.ai/code/{task}",
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    runtime.sampler.sample()
    return runtime


def test_a_get_with_a_loop_names_the_next_pick_and_lists_no_session_before_any_starts(tmp_path: Path) -> None:
    status, body = scheduler("127.0.0.1", "GET", b"", _looping(tmp_path))

    assert status == 200
    assert body["inFlight"] == []
    assert body["next"] == {
        "task": "T-4",
        "title": "Serve it",
        "verdict": "starting",
        "reason": "goes next",
        "priority": "default",
    }


def test_a_get_with_a_loop_lists_each_started_session_and_no_pick_once_nothing_is_left(tmp_path: Path) -> None:
    runtime = _looping(tmp_path)
    runtime.set_enabled(True)
    assert runtime.loop is not None and runtime.loop.tick() == ["T-4"]

    body = scheduler("127.0.0.1", "GET", b"", runtime)[1]

    assert body["inFlight"] == [
        {
            "task": "T-4",
            "title": "Serve it",
            "model": "@agent-standard-high",
            "started": 1000.0,
            "url": "https://claude.ai/code/T-4",
        }
    ]
    assert body["next"] is None


def test_a_get_with_a_loop_names_a_harness_usage_pause(tmp_path: Path) -> None:
    from starpulse.contracts.adapters import StartFailedError

    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    feed.put(
        BoardTask(
            id="T-4", team="demo", title="Serve it", lane="ready", labels=["size-1"], profile="@agent-standard-high"
        )
    )

    def refuse(task: str, **_: object) -> str:
        raise StartFailedError("You've hit your weekly limit · resets 9pm (UTC)")

    runtime = build(
        Scheduler(lane="ready"),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: {"cpu": 5.0, "memory": 5.0},
        clock=lambda: 1000.0,
        start=refuse,
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    runtime.sampler.sample()
    runtime.set_enabled(True)
    assert runtime.loop is not None
    runtime.loop.tick()

    body = scheduler("127.0.0.1", "GET", b"", runtime)[1]

    assert body["pauses"] == [{"harness": "claude", "until": 75_600.0, "reason": "usage limit"}]
    SchedulerStatus.model_validate(body)


def test_every_body_the_route_serves_is_one_the_contract_names(tmp_path: Path) -> None:
    looping = _looping(tmp_path)
    looping.set_enabled(True)
    assert looping.loop is not None and looping.loop.tick() == ["T-4"]

    quiet = _runtime(tmp_path)
    quiet.set_quiet_hours(QUIET)
    for runtime in (_runtime(tmp_path), _looping(tmp_path), looping, quiet):  # no loop; a pick; a session; quiet hours
        SchedulerStatus.model_validate(scheduler("127.0.0.1", "GET", b"", runtime)[1])


# The runtimes' clock reads 1000.0: 00:16:40 UTC, inside this window.
QUIET = {"start": "00:00", "end": "01:00", "timezone": "UTC"}


def test_a_get_defaults_the_harness_to_claude_and_a_put_selects_another(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    assert scheduler("127.0.0.1", "GET", b"", runtime)[1]["harness"] == "claude"
    assert _put(runtime, {"harness": "cursor"})[1]["harness"] == "cursor"
    assert scheduler("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["harness"] == "cursor"


def test_a_put_with_an_empty_harness_is_a_400(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    status, body = _put(runtime, {"harness": ""})

    assert status == 400 and "harness" in body["error"]
    assert runtime.harness.get() == "claude"


def test_a_put_sets_the_quiet_hours_a_restart_keeps_them_and_null_clears_them(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    assert _put(runtime, {"quietHours": QUIET}) == (200, {**scheduler("127.0.0.1", "GET", b"", runtime)[1]})
    assert scheduler("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["quietHours"] == QUIET  # a restarted server
    assert runtime.toggle.get() is False  # setting the window leaves the switch alone

    assert _put(runtime, {"quietHours": None})[1]["quietHours"] is None
    assert scheduler("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["quietHours"] is None


@pytest.mark.parametrize(
    ("window", "names"),
    [
        ({"start": "22:00", "end": "07:00"}, "timezone"),
        ({"start": "25:00", "end": "07:00", "timezone": "UTC"}, "start"),
        ({"start": "22:00", "end": "dawn", "timezone": "UTC"}, "end"),
        ({"start": "22:00", "end": "22:00", "timezone": "UTC"}, "differ"),
        ({"start": "22:00", "end": "07:00", "timezone": "Mars/Base"}, "timezone"),
    ],
)
def test_a_quiet_hours_window_that_cannot_be_read_is_a_400_naming_it_and_changes_nothing(
    tmp_path: Path, window: object, names: str
) -> None:
    runtime = _runtime(tmp_path)

    status, body = _put(runtime, {"quietHours": window})

    assert status == 400 and names in body["error"]
    assert runtime.quiet_hours.get() is None


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"opt_in": True}, "opt_in: Extra inputs are not permitted"),
        ([], "Input should be an object"),
        ("true", "Input should be an object"),
        ({"quietHours": "22:00-07:00"}, "quietHours: Input should be an object"),
    ],
)
def test_a_put_its_model_rejects_is_a_400_naming_the_field_and_changes_nothing(
    tmp_path: Path, body: object, error: str
) -> None:
    runtime = _runtime(tmp_path)

    assert _put(runtime, body) == (400, {"error": f"invalid request: {error}"})
    assert runtime.toggle.get() is False
    assert runtime.quiet_hours.get() is None


def test_a_quiet_hours_put_from_outside_the_private_network_is_refused(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    assert _put(runtime, {"quietHours": QUIET}, "203.0.113.9")[0] == 403
    assert runtime.quiet_hours.get() is None


def test_inside_quiet_hours_the_loop_admits_nothing_and_the_next_pick_waits_for_them(tmp_path: Path) -> None:
    runtime = _looping(tmp_path)
    runtime.set_enabled(True)
    _put(runtime, {"quietHours": QUIET})
    assert runtime.loop is not None

    assert runtime.loop.tick() == []
    assert scheduler("127.0.0.1", "GET", b"", runtime)[1]["next"] == {
        "task": "T-4",
        "title": "Serve it",
        "verdict": "waits",
        "reason": "quiet hours",
        "priority": "default",
    }

    _put(runtime, {"quietHours": None})

    assert runtime.loop.tick() == ["T-4"]


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
    feed = _feed()
    runtime = _runtime(tmp_path, feed)
    runtime.sampler.sample()
    with serve(tmp_path, feed, scheduler=runtime) as served:
        yield served


def _send(server: PageServer, method: str, body: bytes | None, **headers: str) -> tuple[int, dict]:
    request = urllib.request.Request(url(server, "/api/scheduler"), data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read())


def test_the_server_serves_and_flips_the_switch(server: PageServer) -> None:
    status, body = _send(server, "GET", None)
    assert status == 200 and body["enabled"] is False and len(body["dimensions"]) == 4

    status, body = _send(server, "PUT", b'{"enabled": true}', **{"Content-Type": "application/json"})
    assert status == 200 and body["enabled"] is True
    assert _send(server, "GET", None)[1]["enabled"] is True


def test_the_server_refuses_a_put_that_is_not_json_or_comes_from_another_site(server: PageServer) -> None:
    assert _send(server, "PUT", b'{"enabled": true}', **{"Content-Type": "text/plain"})[0] == 415
    foreign = {"Content-Type": "application/json", "Origin": "https://evil.example"}
    assert _send(server, "PUT", b'{"enabled": true}', **foreign)[0] == 403
    assert _send(server, "GET", None)[1]["enabled"] is False


def test_scheduler_put_atomic_a_bad_harness_is_a_400_and_keeps_the_quiet_hours(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    status, body = _put(runtime, {"quietHours": {"start": "22:00", "end": "07:00", "timezone": "UTC"}, "harness": ""})

    assert status == 400 and "harness" in body["error"]
    assert runtime.quiet_hours.get() is None


def test_scheduler_settle_writes_needs_attention_section_and_moves_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheduler's settle is the board's edit to its attention lane with the run's reason: the reason lands in the
    task's `## Needs attention` section, so the lane's guard passes and the task moves."""
    from tests.unit.board.test_native_lifecycle import _in_progress, _text

    guard = {
        "on": {"to": "Needs attention"},
        "require": {"section": {"heading": "Needs attention", "nonempty": True}},
        "reason": "Needs attention needs a non-empty ## Needs attention reason in the description",
    }
    _, built = _in_progress(tmp_path, monkeypatch, rules=[guard])
    reason = "Scheduler settled task-1: its session was idle for 31 minutes."

    written = built.edit("task-1", {"status": built.roles.attention}, reason)

    assert written.ok, written.output
    task_text = _text(tmp_path, "task-1")
    assert "status: Needs attention\n" in task_text
    assert f"## Needs attention\n\n<!-- SECTION:NEEDS_ATTENTION:BEGIN -->\n{reason}\n" in task_text
