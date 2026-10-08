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


def test_the_what_if_route_takes_the_lanes_it_is_asked_for():
    ids = dict(zip(("from", "to"), ("In Progress", "review"), strict=True))
    path = pl.fill(pl.READS["/api/level/what-if"], ids)
    assert path == "/api/level/what-if?hours=168&from=In%20Progress&to=review&p=0.5"


def test_every_read_route_the_server_answers_is_timed():
    server = (Path(__file__).resolve().parents[1] / "starpulse" / "api" / "server.py").read_text()
    for route in pl.READS:
        assert route.removesuffix("/<id>") in server, route


def test_a_local_build_answers_every_page_url_but_its_assets_with_its_index(tmp_path):
    assert pl.local_file(tmp_path, "http://h/assets/index-1.js?v=2") == tmp_path / "assets" / "index-1.js"
    assert pl.local_file(tmp_path, "http://h/") == tmp_path / "index.html"
    assert pl.local_file(tmp_path, "http://h/flow/in-progress") == tmp_path / "index.html"


def test_the_viewer_runs_the_whole_bench_in_a_scope_weighted_over_the_host_load():
    command = pl.viewer_command(["bench/page_latency.py", "http://h", "--viewer"], "/usr/bin/python3")
    assert command == [
        "systemd-run", "--user", "--scope", "--quiet", "-p", f"CPUWeight={pl.VIEWER_CPU_WEIGHT}",
        "--", "/usr/bin/python3", "bench/page_latency.py", "http://h", "--viewer",
    ]  # fmt: skip


def test_the_viewer_enters_its_scope_once(monkeypatch):
    execs: list[list[str]] = []
    monkeypatch.delenv(pl.VIEWER_ENV, raising=False)
    monkeypatch.setattr(pl.os, "execvp", lambda file, args: execs.append([file, *args]))
    pl.enter_viewer(["bench/page_latency.py", "http://h", "--viewer"])
    assert execs and execs[0][0] == "systemd-run"
    assert pl.os.environ[pl.VIEWER_ENV] == "1"

    execs.clear()
    pl.enter_viewer(["bench/page_latency.py", "http://h", "--viewer"])
    assert execs == []


def _runs(*p95s: float) -> list[list[pl.Row]]:
    """One run per p95: 18 samples of 1 ms and two of that p95, so the run's nearest-rank p95 is the value."""
    return [[pl.Row("switch", "interaction", 50.0, [1.0] * 18 + [p95, p95])] for p95 in p95s]


def test_a_surface_is_judged_on_the_median_run_p95_so_one_starved_run_does_not_fail_it():
    (row,) = pl.median_run(_runs(10.0, 900.0, 20.0))
    assert row.p95 == 20.0
    assert row.over is False
    assert "median of 3 runs" in row.note


def test_a_surface_over_budget_in_most_runs_fails_whatever_the_best_run_read():
    (row,) = pl.median_run(_runs(10.0, 90.0, 80.0))
    assert row.p95 == 80.0
    assert row.over is True


def test_an_even_number_of_runs_judges_the_lower_median_so_a_tie_does_not_fail_on_noise():
    (row,) = pl.median_run(_runs(10.0, 90.0))
    assert row.p95 == 10.0


def test_one_run_is_reported_as_it_ran():
    runs = _runs(90.0)
    assert pl.median_run(runs) == runs[0]


def test_rows_are_matched_by_name_and_a_row_one_run_lacks_is_judged_on_the_runs_that_have_it():
    first = [pl.Row("a", "request", 50.0, [1.0]), pl.Row("stream `move` to paint", "stream", 50.0, [99.0])]
    second = [pl.Row("a", "request", 50.0, [2.0])]
    rows = {r.name: r for r in pl.median_run([first, second])}
    assert list(rows) == ["a", "stream `move` to paint"]
    assert rows["a"].p95 == 1.0
    assert rows["stream `move` to paint"].p95 == 99.0


def test_a_surface_no_run_sampled_keeps_its_note():
    runs = [[pl.Row("docs/<id>", "request", 50.0, note="no record to read")] for _ in range(3)]
    (row,) = pl.median_run(runs)
    assert row.samples == [] and row.note == "no record to read"


def test_a_ceiling_raises_one_rows_budget_and_says_so():
    rows = [pl.Row("first paint", "interaction", 50.0, [79.0]), pl.Row("switch", "interaction", 50.0, [90.0])]
    pl.apply_ceilings(rows, ["first paint=120"])
    assert [r.budget for r in rows] == [120.0, 50.0]
    assert [r.over for r in rows] == [False, True]
    assert "ceiling 120" in rows[0].note
    assert rows[1].note == ""


def test_a_ceiling_still_fails_a_row_that_passes_it():
    rows = [pl.Row("first paint", "interaction", 50.0, [130.0])]
    pl.apply_ceilings(rows, ["first paint=120"])
    assert rows[0].over


def test_a_ceiling_naming_no_row_is_refused():
    with pytest.raises(ValueError, match="no row named first paintt"):
        pl.apply_ceilings([pl.Row("first paint", "interaction", 50.0, [1.0])], ["first paintt=120"])
