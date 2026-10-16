"""GET /api/pulls against StarPulse's own store: the pull requests it read from GitHub, filtered and dated."""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls.pulls import PullStore
from starpulse.tests.machines import MACHINES


def _pull(repo: str, number: int, state: str, body: str, fetched: float) -> dict:
    return {
        "repo": repo,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": body,
        "checks": "pass",
        "requiredChecks": [{"name": "lint", "result": "pass"}],
        "threads": 1,
        "unresolvedThreads": [{"id": f"PRRT_{number}", "author": "coderabbitai"}],
        "headRefName": f"claude/task-{number}-thing",
        "updatedAt": "2026-10-07T12:00:00Z",
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": fetched,
    }


def _get(server: ThreadingHTTPServer, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/pulls{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _numbers(server: ThreadingHTTPServer, query: str) -> list[tuple[str, int]]:
    status, body = _get(server, query)
    assert status == 200
    return [(pull["repo"], pull["number"]) for pull in body["pulls"]]


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save(
        [
            _pull("acme/widgets", 1, "OPEN", "Session: aaa-111", 100.0),
            _pull("acme/widgets", 2, "MERGED", "Session: bbb-222", 101.0),
            _pull("acme/skills", 1, "OPEN", "Session: bbb-222", 102.5),
        ]
    )
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=store) as server:
        yield server


def test_no_filter_answers_every_record_with_its_fetched_at(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "")

    assert status == 200
    assert [(pull["repo"], pull["number"], pull["fetchedAt"]) for pull in body["pulls"]] == [
        ("acme/skills", 1, 102.5),
        ("acme/widgets", 1, 100.0),
        ("acme/widgets", 2, 101.0),
    ]
    assert body["pulls"][1] == _pull("acme/widgets", 1, "OPEN", "Session: aaa-111", 100.0)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?repo=acme/widgets", [("acme/widgets", 1), ("acme/widgets", 2)]),
        ("?number=1", [("acme/skills", 1), ("acme/widgets", 1)]),
        ("?state=OPEN", [("acme/skills", 1), ("acme/widgets", 1)]),
        ("?state=open", [("acme/skills", 1), ("acme/widgets", 1)]),
        ("?body_contains=bbb-222", [("acme/skills", 1), ("acme/widgets", 2)]),
        ("?body_contains=bbb-222&state=OPEN", [("acme/skills", 1)]),
        ("?repo=acme/widgets&number=2&state=MERGED&body_contains=Session", [("acme/widgets", 2)]),
        ("?body_contains=nothing-has-this", []),
    ],
)
def test_each_filter_narrows_the_records_and_they_combine(
    server: ThreadingHTTPServer, query: str, expected: list[tuple[str, int]]
) -> None:
    assert _numbers(server, query) == expected


@pytest.mark.parametrize("query", ["?number=one", "?state=DRAFT"])
def test_a_filter_that_cannot_match_is_refused(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _get(server, query)

    assert status == 400
    assert "error" in body


def test_a_repeated_read_is_answered_without_asking_the_store_again_until_it_changes(tmp_path: Path) -> None:
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save([_pull("acme/widgets", 1, "OPEN", "Session: aaa-111", 100.0)])
    asked = []
    find = store.find
    store.find = lambda *a, **k: asked.append(a) or find(*a, **k)  # type: ignore[method-assign]
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=store) as server:
        for _ in range(3):
            _get(server, "")
        store.save([_pull("acme/widgets", 2, "OPEN", "Session: bbb-222", 101.0)])
        numbers = _numbers(server, "")

    assert len(asked) == 2
    assert numbers == [("acme/widgets", 1), ("acme/widgets", 2)]


def test_metrics_serves_the_store_age_gauge_as_prometheus_text(tmp_path: Path) -> None:
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save([_pull("acme/widgets", 1, "OPEN", "", 940.0)])

    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=store, clock=lambda: 1000.0) as server:
        with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
            body = resp.read().decode()
            content_type = resp.headers["Content-Type"]

    assert content_type.startswith("text/plain")
    assert 'starpulse_pull_store_age_seconds{repo="acme/widgets"} 60' in body.splitlines()


def test_metrics_serves_the_server_process_gauges_with_or_without_a_pull_store(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES)) as server:
        with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
            samples = dict(line.split() for line in resp.read().decode().splitlines() if not line.startswith("#"))

    assert int(samples["process_resident_memory_bytes"]) > 0
    assert int(samples["process_threads"]) > 0
    assert int(samples["process_open_fds"]) > 0
    assert float(samples["process_start_time_seconds"]) > 1_700_000_000


def _slow_reads(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "slow_read" in r.getMessage()]


def _slow_store(tmp_path: Path, seconds: float) -> PullStore:
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    store.save([_pull("acme/widgets", 1, "OPEN", "Session: aaa-111", 100.0)])
    find = store.find

    def slow_find(*args: object, **kwargs: object) -> list[dict]:
        time.sleep(seconds)
        return find(*args, **kwargs)

    store.find = slow_find  # type: ignore[method-assign]
    return store


def test_slow_read_logs_one_line_with_the_query_and_each_phase_in_seconds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=_slow_store(tmp_path, 0.2), slow_read_s=0.1) as server:
        _get(server, "?repo=acme/widgets")

    (line,) = _slow_reads(caplog)
    assert "query=repo=acme/widgets" in line
    fields = dict(re.findall(r"(queue_s|compute_s|write_s|in_flight|busy|streams)=([0-9.]+)", line))
    assert float(fields["compute_s"]) >= 0.2
    assert set(fields) == {"queue_s", "compute_s", "write_s", "in_flight", "busy", "streams"}
    assert fields["in_flight"] == "1"


def test_slow_read_logs_nothing_for_a_fast_read_or_a_slow_read_of_another_route(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=_slow_store(tmp_path, 0.0), slow_read_s=60.0) as server:
        _get(server, "")
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=_slow_store(tmp_path, 0.0), slow_read_s=0.0) as server:
        urllib.request.urlopen(url(server, "/metrics"), timeout=5).read()

    assert _slow_reads(caplog) == []


def _counting_store(tmp_path: Path, seconds: float = 0.0) -> tuple[PullStore, list[tuple]]:
    store = _slow_store(tmp_path, seconds)
    calls: list[tuple] = []
    find = store.find

    def counted(*args: object, **kwargs: object) -> list[dict]:
        calls.append(args)
        return find(*args, **kwargs)

    store.find = counted  # type: ignore[method-assign]
    return store, calls


def test_a_save_computes_the_unfiltered_answer_before_any_reader_asks(tmp_path: Path) -> None:
    store, calls = _counting_store(tmp_path)
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=store) as server:
        store.save([_pull("acme/widgets", 2, "OPEN", "Session: bbb-222", 101.0)])
        computed_by_save = len(calls)
        status, body = _get(server, "")

    assert (computed_by_save, len(calls), status) == (1, 1, 200)
    assert [pull["number"] for pull in body["pulls"]] == [1, 2]


def test_readers_asking_together_for_an_answer_nobody_holds_share_one_computation(tmp_path: Path) -> None:
    store, calls = _counting_store(tmp_path, seconds=0.3)
    with serve(tmp_path, BoardFeed(machines=MACHINES), pulls=store) as server:
        with ThreadPoolExecutor(6) as pool:
            answers = list(pool.map(lambda _: _get(server, "?state=open"), range(6)))

    assert len(calls) == 1
    assert [status for status, _ in answers] == [200] * 6
