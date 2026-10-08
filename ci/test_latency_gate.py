"""The pull-request latency gate: the CI job that runs `bench/page_latency.py` against `ci/seeded_server.py`, and the
seeded server it measures. The harness's own rules are `ci/test_page_latency.py`."""

from __future__ import annotations

import itertools
import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import demo_workspace
import pytest
import seeded_server
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _gate() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["latency"]


def _runs(job: dict) -> str:
    return "\n".join(step["run"] for step in job["steps"] if "run" in step)


def test_every_pull_request_runs_the_harness_three_times_against_the_seeded_server_on_the_validate_lane():
    job = _gate()
    runs = _runs(job)

    assert job["runs-on"] == ["self-hosted", "validate"]
    assert "ci.seeded_server" in runs
    assert re.search(r"bench/page_latency\.py\s+\S+\s+.*--repeat 3\b", runs), runs
    assert job.get("if", "github.event_name == 'pull_request'") == "github.event_name == 'pull_request'"


def test_the_gate_fails_the_job_on_a_row_over_budget_and_never_continues_on_error():
    job = _gate()
    bench = next(step for step in job["steps"] if "page_latency.py" in step.get("run", ""))

    assert not job.get("continue-on-error")
    assert not bench.get("continue-on-error")
    assert "|| true" not in bench["run"]
    # the harness exits 1 on a row over budget or an untimed request; the step must exit with that status
    assert re.search(r'exit "?\$(status|\?)"?', bench["run"]), bench["run"]


def test_the_gate_builds_the_page_the_server_draws_before_it_starts_the_server():
    order = [step.get("run", "") for step in _gate()["steps"]]
    built = next(i for i, run in enumerate(order) if "run build" in run)
    served = next(i for i, run in enumerate(order) if "ci.seeded_server" in run)

    assert built < served


def test_the_job_is_not_a_gate_on_the_green_dispatch():
    """The dispatch is a push to main's; the gate judges pull requests, and a noisy runner must not hold a green SHA."""
    dispatch = yaml.safe_load(WORKFLOW.read_text())["jobs"]["dispatch"]

    assert "latency" not in dispatch["needs"]


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
