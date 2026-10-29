"""The seeded server the latency gate measures. The nightly latency gate (`ci/latency_gate.sh`) runs `bench/page_latency.py` against
it; no pull request does. The harness's own rules are `ci/test_page_latency.py`."""

from __future__ import annotations

import itertools
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import demo_workspace
import pytest
import seeded_server
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.page_server import PageServer
from tests.summaries import assert_matches_rebuild

# Each test starts the seeded server, a budget-sized start; they run in the nightly only.
pytestmark = pytest.mark.nightly

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PageServer]:
    # `ci/preview.toml` names its board `ci.demo_workspace`, which needs the repository root on the import path
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT))
        server = seeded_server.serve(0, tmp_path_factory.mktemp("gate"))
    server.start()
    yield server
    server.close()


def _get(server: PageServer, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_the_seeded_server_holds_a_kanban_a_task_record_and_its_history(seeded: PageServer) -> None:
    status, snapshot = _get(seeded, "/api/snapshot")
    board = next(flow for flow in snapshot["flows"] if flow["name"] == "board" or flow.get("id") == "board")
    task = board["agents"][0]["id"]

    assert status == 200 and len(board["agents"]) > 50
    assert _get(seeded, f"/api/task/{task}")[1]["record"]["acceptanceCriteria"]
    assert len(_get(seeded, f"/api/history?task={task}")[1]["path"]) >= 1


def test_the_seeded_server_answers_the_scheduler_milestone_and_doc_routes_with_records(
    seeded: PageServer,
) -> None:
    status, scheduler = _get(seeded, "/api/scheduler")
    assert status == 200 and scheduler["dimensions"], scheduler

    for route, key in (("/api/milestones", "milestones"), ("/api/docs", "docs")):
        status, listing = _get(seeded, route)
        assert status == 200 and listing[key], (route, listing)
        assert _get(seeded, f"{route}/{listing[key][0]['id']}")[0] == 200, route


def test_every_seeded_route_follows_a_transition_the_board_machine_allows() -> None:
    machine = demo_workspace.board({"type": "demo_workspace"}, ROOT / "ci").machines(lambda n: n, [])["board"]
    allowed = {(t["source"], t["target"]) for t in machine["transitions"]}
    routes = [*seeded_server.ROUTES.values(), *seeded_server.DETOURS.values()]

    for route in routes:
        assert all(step in allowed for step in itertools.pairwise(route)), route


def test_the_seeded_history_holds_every_lane_each_task_passed_through_with_summaries_that_match_its_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 1_800_000_000.0
    monkeypatch.syspath_prepend(str(ROOT))
    server, feed, tasks = seeded_server.build(0, tmp_path, now=now)
    server.socket.close()
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", feed.machines)

    assert_matches_rebuild(store)
    assert tasks
    for index, final in enumerate(seeded_server.lanes()):
        route = [lane for lane, _ in seeded_server.steps(final, index, now)]
        assert [move["to"] for move in store.lane_path(f"DEMO-{index}")] == route
