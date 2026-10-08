"""The page-latency harness's rules: percentiles, which surface a request is, what counts as untimed, and the verdict."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "bench" / "page_latency.py"
_spec = importlib.util.spec_from_file_location("page_latency", _PATH)
assert _spec and _spec.loader
pl = sys.modules["page_latency"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)


def test_the_percentile_is_the_nearest_rank():
    samples = [float(n) for n in range(1, 101)]
    assert pl.percentile(samples, 95) == 95.0
    assert pl.percentile(samples, 50) == 50.0
    assert pl.percentile([7.0], 95) == 7.0
    assert pl.percentile([], 95) is None


@pytest.mark.parametrize(
    ("url", "route"),
    [
        ("http://h:8766/api/level?hours=168", "/api/level"),
        ("http://h:8766/api/task/TASK-12", "/api/task/<id>"),
        ("http://h:8766/api/task/TASK%2012", "/api/task/<id>"),
        ("http://h:8766/api/milestones/m-3", "/api/milestones/<id>"),
        ("http://h:8766/api/milestones/edit", "/api/milestones/edit"),
        ("http://h:8766/api/docs/archive", "/api/docs/archive"),
        ("http://h:8766/api/milestones", "/api/milestones"),
        ("http://h:8766/assets/index.js", None),
        ("http://h:8766/", None),
    ],
)
def test_a_request_is_a_sample_of_its_route(url, route):
    assert pl.surface(url) == route


def test_a_page_request_no_row_times_is_untimed():
    requested = [
        "http://h/api/level?hours=1",
        "http://h/api/task/TASK-1",
        "http://h/api/new-thing?x=1",
        "http://h/a.js",
    ]
    assert pl.untimed(requested, ["/api/level", "/api/task/<id>"]) == ["/api/new-thing"]
    assert pl.untimed(requested[:2], ["/api/level", "/api/task/<id>"]) == []


def test_a_row_is_over_when_its_p95_passes_its_budget():
    # one slow sample of 20 is the p100, not the p95
    assert pl.Row("r", "request", 50.0, [10.0] * 19 + [60.0]).over is False
    assert pl.Row("r", "request", 50.0, [10.0] * 18 + [60.0, 60.0]).over is True
    assert pl.Row("r", "request", 50.0).over is False


def test_the_run_fails_on_a_row_over_budget_or_an_untimed_request():
    fast, slow = pl.Row("a", "request", 50.0, [1.0]), pl.Row("b", "request", 50.0, [99.0])
    assert pl.verdict([fast], []) == 0
    assert pl.verdict([fast, slow], []) == 1
    assert pl.verdict([fast], ["/api/new-thing"]) == 1


def test_the_table_marks_rows_over_budget_and_lists_untimed_requests():
    out = pl.table([pl.Row("/api/x", "request", 50.0, [99.0])], ["/api/y"])
    assert "OVER" in out.splitlines()[1]
    assert out.splitlines()[-1] == "UNTIMED request the page made: /api/y"


def test_a_route_is_filled_from_the_records_the_server_holds():
    snapshot = {"flows": [{"agents": []}, {"agents": [{"id": "TASK-7"}]}]}
    ids = pl.ids_of(snapshot, {"milestones": [{"id": "m-1"}]}, [{"id": "doc-2"}])
    assert ids == {"task": "TASK-7", "milestone": "m-1", "doc": "doc-2"}
    assert pl.fill("/api/task/{task}", ids) == "/api/task/TASK-7"
    assert pl.fill("/api/task/{task}", {}) is None


def test_every_read_route_the_server_answers_is_timed():
    server = (Path(__file__).resolve().parents[1] / "starpulse" / "api" / "server.py").read_text()
    for route in pl.READS:
        assert route.removesuffix("/<id>") in server, route


def test_a_local_build_answers_every_page_url_but_its_assets_with_its_index(tmp_path):
    assert pl.local_file(tmp_path, "http://h/assets/index-1.js?v=2") == tmp_path / "assets" / "index-1.js"
    assert pl.local_file(tmp_path, "http://h/") == tmp_path / "index.html"
    assert pl.local_file(tmp_path, "http://h/flow/in-progress") == tmp_path / "index.html"
