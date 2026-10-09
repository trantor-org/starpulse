"""The load test's rules: where an event-stream event ends, and which routes break the budget under load."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(_BENCH))
# Locust monkey-patches the interpreter with gevent on import, which a test process cannot survive; the rules need none.
sys.modules.setdefault("gevent", None)
_spec = importlib.util.spec_from_file_location("load", _BENCH / "load.py")
assert _spec and _spec.loader
load = sys.modules["load"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load)


def test_an_event_ends_at_its_blank_line():
    lines = [
        b"event: snapshot\n",
        b"data: ref /api/events/body/abc\n",
        b"\n",
        b"event: ledgers\n",
        b"data: {}\n",
        b"\n",
    ]
    assert list(load.events(lines)) == [("snapshot", "ref /api/events/body/abc"), ("ledgers", "{}")]


def test_a_comment_and_an_unnamed_event_are_messages():
    lines = [b": keepalive\n", b"\n", b"data: a\r\n", b"data: b\r\n", b"\r\n"]
    assert list(load.events(lines)) == [("message", "a\nb")]


def test_a_stream_cut_mid_event_yields_nothing_for_it():
    assert list(load.events([b"event: snapshot\n", b"data: x\n"])) == []


def test_a_route_over_the_budget_fails_the_run():
    p95s = {"/api/snapshot": 12.0, "/api/level": 80.0, "Aggregated": 60.0}
    assert load.over_budget(p95s, {}) == ["/api/level p95 80 ms > 50 ms"]


def test_a_failed_request_fails_the_run_even_when_fast():
    assert load.over_budget({"/api/pulls": 5.0}, {"/api/pulls": 3}) == ["/api/pulls 3 failed"]


def test_a_run_inside_the_budget_passes():
    assert load.over_budget({"/api/snapshot": 49.0, "/api/events first snapshot": 50.0}, {}) == []


def test_the_discovery_reads_are_not_judged():
    assert load.over_budget({load.DISCOVERY: 900.0}, {load.DISCOVERY: 2}) == []
