"""Every GET /api route answers a body its pydantic model accepts: the contract the page's generated types come from."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from sqlalchemy import create_engine

from starpulse._internal.autopilot.runtime import build
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.contracts.api import RESPONSES
from starpulse._internal.config.level import Level, Orbit, Terminal
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.search import SearchIndex
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.harnesses.telemetry import TelemetryLog, signals
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES
from starpulse.tests.unit.level.test_analytics import NOW, ROWS
from starpulse.tests.unit.feed.test_board_feed import _paged_feed

#: Every GET route the server answers with JSON, as the page asks for it; `/api/events` is a stream, tested apart.
ROUTES = (
    "/api/snapshot",
    "/api/merges",
    "/api/machines",
    "/api/history?task=T-1",
    "/api/history?task=T-1&flow=in-progress",
    "/api/pulls",
    "/api/analytics/health",
    "/api/analytics/sessions",
    "/api/harnesses",
    "/api/history-window",
    "/api/forwarding",
    "/api/autopilot",
    "/api/doctor",
    "/api/task/T-1",
    "/api/search?q=T-1",
    "/api/level?hours=48",
    "/api/level/trajectories?hours=48",
)
LEVEL = Level("board", "done", (Terminal("done", "goal"),), gates=("review",), orbit=Orbit("working", ("in_progress", "review")))


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("T-1", "In Progress"))
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, (name, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"{'a' if name in 'AB' else 'b'}/{i}", name, new, at)
    store.record_lane("l0", "T-1", "In Progress", NOW - 3600)
    runtime = build(Autopilot(), tmp_path / "autopilot.json", feed, probe=lambda: {"cpu": 10.0, "memory": 20.0})
    runtime.sampler.sample()
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    for line in (FIXTURES / "claude_code" / "otlp.ndjson").read_text().splitlines():
        telemetry.publish(signals(json.loads(line)))
    search = SearchIndex.open(create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}"))
    assert search is not None
    search.index(task("T-1", "In Progress"))
    with serve(
        tmp_path,
        feed,
        history=store,
        read=lambda t: {"title": t},
        clock=lambda: NOW,
        level=LEVEL,
        autopilot=runtime,
        telemetry=telemetry,
        search=search,
    ) as server:
        yield server


def _model(route: str) -> object | None:
    path = route.partition("?")[0]
    return RESPONSES.get("/api/task/" if path.startswith("/api/task/") else path)


def _validate(server: ThreadingHTTPServer, route: str) -> None:
    model = _model(route)
    assert model is not None, f"{route} has no response model in contracts.api.RESPONSES"

    with urllib.request.urlopen(url(server, route), timeout=5) as resp:
        body = json.loads(resp.read())

    TypeAdapter(model).validate_python(body)


@pytest.mark.parametrize("route", ROUTES)
def test_api_contract_get_route_body_validates_against_its_model(server: ThreadingHTTPServer, route: str) -> None:
    _validate(server, route)


@pytest.mark.parametrize("route", ["/api/snapshot", "/api/merges"])
def test_api_contract_a_merge_ledger_with_runs_failures_and_pins_validates_against_its_model(
    tmp_path: Path, route: str
) -> None:
    with serve(tmp_path, _paged_feed()) as server:
        _validate(server, route)
