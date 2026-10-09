"""The seeded server the latency gate measures. trantor's nightly whole-repo gate runs `bench/page_latency.py` against
it (`make starpulse-latency`); no pull request does. The harness's own rules are `ci/test_page_latency.py`."""

from __future__ import annotations

import itertools
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import demo_workspace
import pytest
import seeded_server

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ThreadingHTTPServer]:
    # `ci/preview.toml` names its board `ci.demo_workspace`, which needs the repository root on the import path
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT))
        server = seeded_server.serve(0, tmp_path_factory.mktemp("gate"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_the_seeded_server_holds_a_kanban_a_task_record_and_its_history(seeded: ThreadingHTTPServer) -> None:
    status, snapshot = _get(seeded, "/api/snapshot")
    board = next(flow for flow in snapshot["flows"] if flow["name"] == "board" or flow.get("id") == "board")
    task = board["agents"][0]["id"]

    assert status == 200 and len(board["agents"]) > 50
    assert _get(seeded, f"/api/task/{task}")[1]["record"]["acceptanceCriteria"]
    assert len(_get(seeded, f"/api/history?task={task}")[1]["path"]) >= 1


def test_the_seeded_server_answers_the_level_routes_a_hubless_preview_cannot(seeded: ThreadingHTTPServer) -> None:
    for route in ("/api/level", "/api/level/trajectories"):
        assert _get(seeded, f"{route}?hours=168")[0] == 200, route
    assert _get(seeded, "/api/level/what-if?hours=168&from=in_progress&to=review&p=0.5")[0] == 200


def test_every_seeded_route_follows_a_transition_the_board_machine_allows() -> None:
    machine = demo_workspace.board({"type": "demo_workspace"}, ROOT / "ci").machines(lambda n: n, [])["board"]
    allowed = {(t["source"], t["target"]) for t in machine["transitions"]}
    routes = [*seeded_server.ROUTES.values(), *seeded_server.DETOURS.values()]

    for route in routes:
        assert all(step in allowed for step in itertools.pairwise(route)), route
