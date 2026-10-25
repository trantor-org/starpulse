"""Every GET /api route answers a body its pydantic model accepts: the contract the page's generated types come from."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import replace

import pytest
from pydantic import TypeAdapter
from sqlalchemy import create_engine

from starpulse._internal.config.scheduler import Scheduler
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.search import SearchIndex
from starpulse._internal.harnesses.telemetry import Signal, TelemetryLog, signals
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse._internal.scheduler.runtime import build
from starpulse._internal.server.page_server import PageServer
from starpulse.contracts.api.registry import BODIES, RESPONSES
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.history import HistoryStore
from starpulse.tests.fake_board import bare_board
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.tests.unit.feed.test_board_feed import _paged_feed
from starpulse.tests.unit.flow_metrics.test_analytics import NOW, ROWS
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES

#: Every GET route the server answers with JSON, as the page asks for it; `/api/events` is a stream, tested apart.
ROUTES = (
    "/api/snapshot",
    "/api/machines",
    "/api/history?task=T-1",
    "/api/history?task=T-1&flow=in-progress",
    "/api/pulls",
    "/api/analytics/health",
    "/api/analytics/sessions?hours=1",
    "/api/analytics/steps?hours=1",
    "/api/analytics/missed-loads?hours=1",
    "/api/analytics/trace-clusters?outliers=2&hours=1",
    "/api/harnesses",
    "/api/history-window",
    "/api/scheduler",
    "/api/doctor",
    "/api/task/T-1",
    "/api/search?q=T-1",
)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PageServer]:
    """One server for the module: every test reads it with GET and none writes to it."""
    tmp_path = tmp_path_factory.mktemp("contract")
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("T-1", "In Progress"))
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, (name, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"{'a' if name in 'AB' else 'b'}/{i}", name, new, at)
    store.record_lane("l0", "T-1", "In Progress", NOW - 3600)
    runtime = build(
        Scheduler(),
        tmp_path,
        EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}"),
        feed,
        probe=lambda: {"cpu": 10.0, "memory": 20.0},
    )
    runtime.sampler.sample()
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    recorded = [
        sg
        for line in (FIXTURES / "claude_code" / "otlp.ndjson").read_text().splitlines()
        for sg in signals(json.loads(line))
    ]
    shift = max(sg.time for sg in recorded) - (NOW - 60)  # the exports ended a minute before the clock
    telemetry.publish([replace(sg, time=sg.time - shift) for sg in recorded])
    telemetry.publish(
        [Signal("claude-code", "anchor", "prompt", NOW - 7200, "anchor:prompt")]
    )  # a history of two hours
    search = SearchIndex.open(create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}"))
    assert search is not None
    search.index(task("T-1", "In Progress"))
    with serve(
        tmp_path,
        feed,
        bare_board(read=lambda t: {"title": t}),
        history=store,
        clock=lambda: NOW,
        scheduler=runtime,
        telemetry=telemetry,
        search=search,
    ) as server:
        yield server


def _model(route: str) -> object | None:
    path = route.partition("?")[0]
    prefix = next((p for p in ("/api/task/", "/api/ledger/") if path.startswith(p)), path)
    return RESPONSES.get(prefix)


def _validate(server: PageServer, route: str) -> None:
    model = _model(route)
    assert model is not None, f"{route} has no response model in contracts.api.registry.RESPONSES"

    with urllib.request.urlopen(url(server, route), timeout=5) as resp:
        body = json.loads(resp.read())

    TypeAdapter(model).validate_python(body)


@pytest.mark.parametrize("route", ROUTES)
def test_api_contract_get_route_body_validates_against_its_model(server: PageServer, route: str) -> None:
    _validate(server, route)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("sessions", "sessions"),
        ("steps", "session_steps"),
        ("missed-loads", "missed_loads"),
        ("trace-clusters", "trace_clusters"),
    ],
)
def test_api_contract_a_telemetry_window_longer_than_the_history_validates_against_its_body_model(
    server: PageServer, path: str, kind: str
) -> None:
    route = f"/api/analytics/{path}?hours=3"

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(url(server, route), timeout=5)

    body = json.loads(refused.value.read())
    assert (refused.value.code, body["history_s"]) == (400, 7200)
    TypeAdapter(BODIES[kind]).validate_python(body)


@pytest.fixture(scope="module")
def paged_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PageServer]:
    with serve(tmp_path_factory.mktemp("paged"), _paged_feed()) as server:
        yield server


@pytest.mark.parametrize("route", ["/api/snapshot", "/api/ledger/MERGED"])
def test_api_contract_a_merge_ledger_with_runs_failures_and_pins_validates_against_its_model(
    paged_server: PageServer, route: str
) -> None:
    _validate(paged_server, route)
