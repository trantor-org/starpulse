"""Periodic pull sync lists for drift; full GraphQL detail only on miss, push, or drift."""

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pull_store import (
    DRIFT_METRIC,
    PullSync,
    drift_count,
    drift_counter,
    refresh_repository,
)
from starpulse._internal.pulls.pulls import PullStore

REPO = "acme/widgets"


def _open_node(number: int, *, updated: str = "2020-01-01T00:00:00Z") -> dict:
    return {"number": number, "state": "OPEN", "updatedAt": updated}


def _pr_node(number: int) -> dict:
    return {
        "number": number,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "feat",
        "headRefOid": "abc",
        "body": f"PR {number}",
        "updatedAt": "2020-01-01T00:00:00Z",
        "createdAt": "2020-01-01T00:00:00Z",
        "mergedAt": None,
        "mergeCommit": None,
        "files": {"nodes": []},
        "headRef": {"compare": {"aheadBy": 0}},
        "ciCommits": {"nodes": []},
        "timelineItems": {"nodes": []},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": {"nodes": []}}}}]},
        "reviewThreads": {"nodes": []},
    }


def test_reconcile_skips_detail_queries_when_the_store_matches_the_listing() -> None:
    store = PullStore(create_engine("sqlite://"))
    feed = BoardFeed()
    feed.put(task("PROJ-1", "In Progress", references=[f"https://github.com/{REPO}/pull/1"]))
    queries: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        queries.append(query)
        detail = _pr_node(1)
        return {
            "open": {"pageInfo": {"hasNextPage": False}, "nodes": [_open_node(1)]},
            "recent": {"nodes": [_open_node(1)]},
            "p1": detail,
        }

    refresh_repository(REPO, store, 100.0, graphql)
    queries.clear()
    before = drift_count()
    PullSync(store, feed, (), graphql, lambda: 200.0).reconcile()

    assert all("pullRequest(number:" not in q for q in queries)
    assert any("pullRequests(states: OPEN" in q for q in queries)
    assert drift_count() == before
    assert store.find(repo=REPO, number=1)[0]["body"] == "PR 1"


def test_reconcile_full_refreshes_and_counts_drift_when_open_set_differs() -> None:
    store = PullStore(create_engine("sqlite://"))
    feed = BoardFeed()
    feed.put(task("PROJ-1", "In Progress", references=[f"https://github.com/{REPO}/pull/1"]))
    queries: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        queries.append(query)
        nodes = [_open_node(1), _open_node(2)]
        return {
            "open": {"pageInfo": {"hasNextPage": False}, "nodes": nodes},
            "recent": {"nodes": nodes},
            "p1": _pr_node(1),
            "p2": _pr_node(2),
        }

    before = drift_count()
    PullSync(store, feed, (), graphql, lambda: 100.0).reconcile()

    assert any("pullRequest(number: 1)" in q for q in queries)
    assert drift_count() == before + 1
    assert {r["number"] for r in store.find(repo=REPO)} == {1, 2}
    assert DRIFT_METRIC in drift_counter()


def test_run_forever_uses_reconcile_not_blind_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Sync(PullSync):
        def reconcile(self) -> None:
            calls.append("reconcile")
            raise KeyboardInterrupt

        def refresh(self) -> None:
            calls.append("refresh")

    monkeypatch.setattr(Sync, "_idle", lambda self, s: None)
    with pytest.raises(KeyboardInterrupt):
        Sync(PullStore(create_engine("sqlite://")), BoardFeed(), (), lambda *_: {}, lambda: 0.0).run_forever(1.0)

    assert calls == ["reconcile"]
