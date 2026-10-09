"""`/api/autopilot`: the toggle and what the capacity strip draws; a write answers only the private network."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse._internal.autopilot.runtime import Runtime, build
from starpulse._internal.autopilot.sampler import Crossing
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.server.writes import autopilot
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse.contracts.adapters import BoardTask, MachineEvent
from starpulse.tests.machines import MACHINES

HOST = {"cpu": 35.0, "memory": 60.0}


def _feed() -> BoardFeed:
    feed = BoardFeed(machines={**MACHINES, **HARNESS_MACHINES})
    for task, lane, labels in (("T-1", "review", ["size-5"]), ("T-2", "review", []), ("T-3", "to_do", ["size-8"])):
        feed.put(BoardTask(id=task, team="demo", title=task, lane=lane, labels=labels))
    started = MachineEvent(machine="harness", event="SESSION_STARTED", task="T-3", time=time.time())
    MachineTasks(feed).put(started)  # the path a harness adapter's event takes
    return feed


def _runtime(tmp_path: Path, feed: BoardFeed | None = None, crossings: list[Crossing] | None = None) -> Runtime:
    return build(
        Autopilot(),
        tmp_path / "starpulse-autopilot.json",
        feed or _feed(),
        probe=lambda: HOST,
        on_crossing=(crossings if crossings is not None else []).append,
        clock=lambda: 1000.0,
    )


def _put(runtime: Runtime, body: object, source: str = "127.0.0.1") -> tuple[int, dict]:
    return autopilot(source, "PUT", json.dumps(body).encode(), runtime)


def test_a_get_reports_every_dimensions_use_and_limit_and_that_the_autopilot_is_off(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.sampler.sample()

    status, body = autopilot("127.0.0.1", "GET", b"", runtime)

    assert status == 200
    assert body == {
        "enabled": False,
        "sampledAt": 1000.0,
        "dimensions": [
            {"name": "cpu", "use": 35.0, "limit": 80},
            {"name": "memory", "use": 60.0, "limit": 80},
            {"name": "sessions", "use": 1, "limit": 2},  # T-3's harness session is active
            {"name": "review", "use": 8, "limit": 20},  # size-5 plus the unsized task's default 3
        ],
    }


def test_a_get_before_the_first_sample_has_no_readings(tmp_path: Path) -> None:
    assert autopilot("127.0.0.1", "GET", b"", _runtime(tmp_path)) == (
        200,
        {"enabled": False, "sampledAt": None, "dimensions": []},
    )


def test_a_get_answers_any_address(tmp_path: Path) -> None:
    assert autopilot("203.0.113.9", "GET", b"", _runtime(tmp_path))[0] == 200


def test_a_put_turns_the_autopilot_on_and_off_and_a_restart_keeps_it(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    assert _put(runtime, {"enabled": True})[1]["enabled"] is True
    assert autopilot("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["enabled"] is True  # a restarted server

    assert _put(runtime, {"enabled": False})[1]["enabled"] is False
    assert autopilot("127.0.0.1", "GET", b"", _runtime(tmp_path))[1]["enabled"] is False


@pytest.mark.parametrize("source", ["127.0.0.1", "::1", "10.1.2.3", "172.16.0.9", "172.31.255.1", "192.168.1.20"])
def test_a_put_from_loopback_or_rfc_1918_is_taken(tmp_path: Path, source: str) -> None:
    assert _put(_runtime(tmp_path), {"enabled": True}, source)[0] == 200


@pytest.mark.parametrize("source", ["8.8.8.8", "203.0.113.9", "172.32.0.1", "11.0.0.1", "2001:db8::1"])
def test_a_put_from_outside_the_private_network_is_refused_and_changes_nothing(tmp_path: Path, source: str) -> None:
    runtime = _runtime(tmp_path)

    status, body = _put(runtime, {"enabled": True}, source)

    assert status == 403 and "RFC 1918" in body["error"]
    assert runtime.toggle.get() is False


@pytest.mark.parametrize("body", [{}, {"enabled": "yes"}, {"enabled": 1}, {"opt_in": True}, [], "true"])
def test_a_put_that_is_not_a_boolean_is_a_400_and_changes_nothing(tmp_path: Path, body: object) -> None:
    runtime = _runtime(tmp_path)

    status, answer = _put(runtime, body)

    assert status == 400 and "enabled" in answer["error"]
    assert runtime.toggle.get() is False


def test_a_put_that_is_not_json_is_a_400(tmp_path: Path) -> None:
    assert autopilot("127.0.0.1", "PUT", b"{", _runtime(tmp_path))[0] == 400


def test_an_instance_without_a_runtime_has_no_autopilot_route(tmp_path: Path) -> None:
    assert autopilot("127.0.0.1", "GET", b"", None)[0] == 404


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    feed = _feed()
    runtime = _runtime(tmp_path, feed)
    runtime.sampler.sample()
    with serve(tmp_path, feed, autopilot=runtime) as served:
        yield served


def _send(server: ThreadingHTTPServer, method: str, body: bytes | None, **headers: str) -> tuple[int, dict]:
    request = urllib.request.Request(url(server, "/api/autopilot"), data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read())


def test_the_server_serves_and_flips_the_switch(server: ThreadingHTTPServer) -> None:
    status, body = _send(server, "GET", None)
    assert status == 200 and body["enabled"] is False and len(body["dimensions"]) == 4

    status, body = _send(server, "PUT", b'{"enabled": true}', **{"Content-Type": "application/json"})
    assert status == 200 and body["enabled"] is True
    assert _send(server, "GET", None)[1]["enabled"] is True


def test_the_server_refuses_a_put_that_is_not_json_or_comes_from_another_site(server: ThreadingHTTPServer) -> None:
    assert _send(server, "PUT", b'{"enabled": true}', **{"Content-Type": "text/plain"})[0] == 415
    foreign = {"Content-Type": "application/json", "Origin": "https://evil.example"}
    assert _send(server, "PUT", b'{"enabled": true}', **foreign)[0] == 403
    assert _send(server, "GET", None)[1]["enabled"] is False
