"""GET /api/pulls against StarPulse's own store: the pull requests it read from GitHub, filtered and dated."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
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
        "threads": 0,
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
