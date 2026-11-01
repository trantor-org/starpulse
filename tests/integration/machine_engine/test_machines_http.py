"""GET /api/machines: the machines entered from an open machine a page at a time, newest activity first."""

import itertools
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from starpulse.contracts.adapters import MachineEvent
from starpulse.runtime.adapter_kit import serve, url
from starpulse.views.adapters.inbound.page_server import PageServer

from tests.machine_feed import MachineFeed

NOW = 1_000_000.0
IP = "delivery"


def _machine(*states: str, submachines: list[dict] | None = None) -> dict:
    return {
        "states": [
            {"id": s, "name": s, "initial": i == 0, "final": i == len(states) - 1} for i, s in enumerate(states)
        ],
        "transitions": [],
        **({"submachines": submachines} if submachines else {}),
    }


def _session(task: str, state: str, ago: float, sid: str | None = None) -> dict:
    step = {"state": state, "event": state.upper(), "at": NOW - ago}
    return {
        "id": sid or task,
        "task": task,
        "state": state,
        "trail": [step],
        "active": NOW - ago,
        "title": task,
        "model": "",
        "steps": 1,
    }


def _get(server: PageServer, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/machines{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[PageServer]:
    """Five machines entered from `delivery`, `m1` the newest and `m4` and `m5` tied, and `inner` entered from `m1`."""
    monkeypatch.setattr("starpulse.board.board_feed.time.time", lambda: NOW)
    link = {"state": "s", "machine": IP, "exits": {}, "parent": "board", "when": ""}
    machines = {
        "board": _machine("new", "in_progress", "done", submachines=[link | {"state": "in_progress"}]),
        IP: _machine("start", "merged"),
        **{f"m{i}": _machine("a", "b") for i in range(1, 6)},
        "inner": _machine("c", "d"),
    }
    machine = MachineFeed(tmp_path / "events.sqlite", _playable(machines))
    _move(machine, IP, _session("T0", "start", 5000))
    for i, ago in enumerate((100, 200, 300, 400, 400), 1):
        _move(machine, f"m{i}", _session(f"X{i}", "a", ago))
    _move(machine, "m1", _session("T0", "a", 150, "T0-m1"))
    _move(machine, "inner", _session("T0", "c", 100, "T0-inner"))
    with serve(tmp_path, machine.feed) as server:
        yield server


def _playable(machines: dict[str, dict]) -> dict[str, dict]:
    """The machines with the transitions that place each trail step: an event leads along the chain of states, and the
    initial state's own event keeps a task there."""
    playable = {}
    for name, machine in machines.items():
        states = [s["id"] for s in machine["states"]]
        transitions = [{"source": states[0], "target": states[0], "event": states[0].upper()}]
        transitions += [{"source": a, "target": b, "event": b.upper()} for a, b in itertools.pairwise(states)]
        playable[name] = machine | {"transitions": transitions}
    return playable


def _move(feed: MachineFeed, machine: str, session: dict) -> None:
    """Append each trail step of `session` to `machine`, as a writer's machine events arrive."""
    for step in session["trail"]:
        feed.put(MachineEvent(machine=machine, event=step["event"], task=session["task"], time=step["at"]))


def _walk(server: PageServer, limit: int, open_: str = IP) -> list[list[str]]:
    pages: list[list[str]] = []
    query = f"?open={open_}&limit={limit}"
    while True:
        status, body = _get(server, query)
        assert status == 200
        pages.append([m["name"] for m in body["machines"]])
        if not body["more"]:
            return pages
        query = f"?open={open_}&limit={limit}&before={body['machines'][-1]['last']}"


def test_pages_cover_the_rows_newest_activity_first_with_no_overlap_or_gap(server: PageServer) -> None:
    assert _walk(server, 1) == [["m1"], ["m2"], ["m3"], ["m4", "m5"]]


def test_machines_sharing_the_boundary_activity_come_in_one_page_so_a_cursor_neither_repeats_nor_skips(
    server: PageServer,
) -> None:
    assert _walk(server, 2) == [["m1", "m2"], ["m3", "m4", "m5"]]


def test_the_open_machine_chooses_the_level_and_a_page_holds_each_machine_whole(server: PageServer) -> None:
    status, body = _get(server, "?open=m1")

    assert status == 200
    assert body["open"] == "m1"
    assert [m["name"] for m in body["machines"]] == ["inner"]
    assert body["machines"][0]["agents"][0]["task"] == "T0"
    assert body["more"] is False


def test_open_left_out_is_the_in_progress_machine(server: PageServer) -> None:
    status, body = _get(server, "")

    assert (status, body["open"]) == (200, IP)


def test_an_unknown_open_machine_is_404(server: PageServer) -> None:
    status, body = _get(server, "?open=nope")

    assert status == 404
    assert "nope" in body["error"]


@pytest.mark.parametrize("query", ["?before=soon", "?limit=two", "?limit=0", "?limit=101", "?before=nan"])
def test_a_malformed_cursor_or_limit_is_400(server: PageServer, query: str) -> None:
    assert _get(server, query)[0] == 400
