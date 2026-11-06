"""The reconcile pass: it redelivers what the App lists and the inbox lacks, and inserts the pull request facts GitHub never sent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from starpulse.event_log.migrate import migrate_chain
from starpulse.github.adapters.inbound.reconcile import reconcile, run
from starpulse.github.adapters.outbound.cursors import SqlCursors
from starpulse.github.adapters.outbound.inbox import SqlInbox, github_inbox
from starpulse.github.adapters.outbound.reconciled import Reconciled
from starpulse.github.adapters.outbound.rest import Reply
from starpulse.github.model.delivery import Delivery
from starpulse.github.model.events import facts_of
from starpulse.github.model.github_config import GitHub

REPO = "acme/widgets"
HEAD = "a" * 40
MERGE = "b" * 40
NOW = datetime.fromisoformat("2026-11-06T13:00:00+00:00").timestamp()
DELIVERIES = "/app/hook/deliveries?per_page=100"
PULLS = f"/repos/{REPO}/pulls?state=all&sort=updated&direction=desc&per_page=100"
SETTINGS = GitHub("SECRET", repositories=(REPO,))


@dataclass
class Api:
    """GitHub as the pass sees it: a `Reply` per path, answered 304 to the ETag it last gave, and every call kept."""

    routes: dict[str, tuple[str, dict]] = field(default_factory=dict)
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)
    post_status: int = 202
    next: dict[str, str] = field(default_factory=dict)

    def serve(self, path: str, etag: str, body: dict) -> None:
        self.routes[path] = (etag, body)

    def __call__(self, method: str, path: str, etag: str | None) -> Reply:
        self.calls.append((method, path, etag))
        if method == "POST":
            return Reply(self.post_status, {})
        current, body = self.routes.get(path, ("", {"items": []}))
        return Reply(304, {}, current) if etag and etag == current else Reply(200, body, current, self.next.get(path))

    def posts(self) -> list[str]:
        return [path for method, path, _ in self.calls if method == "POST"]

    def gets(self, path: str) -> list[str | None]:
        return [etag for method, called, etag in self.calls if method == "GET" and called == path]


@dataclass
class World:
    inbox: SqlInbox
    cursors: SqlCursors
    api: Api
    counted: Reconciled

    def pass_(self) -> None:
        reconcile(self.api, self.inbox, self.cursors, SETTINGS, self.counted, lambda: NOW)

    def rows(self) -> list[dict]:
        with self.inbox.engine.connect() as db:
            return [dict(row) for row in db.execute(select(github_inbox).order_by(github_inbox.c.id)).mappings()]

    def count(self) -> int:
        with self.inbox.engine.connect() as db:
            return db.execute(select(func.count()).select_from(github_inbox)).scalar_one()


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    inbox = SqlInbox(f"sqlite:///{tmp_path / 'inbox.sqlite'}", migrate_chain)
    yield World(inbox, SqlCursors(inbox.engine), Api(), Reconciled())
    inbox.engine.dispose()


def attempt(attempt_id: int, guid: str, at: str, *, redelivery: bool = False) -> dict:
    return {"id": attempt_id, "guid": guid, "delivered_at": at, "redelivery": redelivery, "status_code": 502}


def pull(number: int, *, state: str = "closed", merged: bool = True, updated: str = "2026-11-06T12:00:00Z") -> dict:
    return {
        "number": number,
        "state": state,
        "merged_at": updated if merged else None,
        "merge_commit_sha": MERGE if merged else None,
        "updated_at": updated,
        "head": {"sha": HEAD},
        "user": {"type": "User"},
    }


def suite(suite_id: int, conclusion: str, number: int) -> dict:
    return {"id": suite_id, "status": "completed", "conclusion": conclusion, "pull_requests": [{"number": number}]}


def test_a_delivery_the_app_lists_but_the_inbox_lacks_is_redelivered_once_and_one_it_holds_is_not(world: World) -> None:
    world.inbox.save(Delivery("g-held", "push", "", REPO, b"{}"))
    world.api.serve(
        DELIVERIES,
        '"d1"',
        {
            "items": [
                attempt(5, "g-redelivered", "2026-11-06T12:50:00Z", redelivery=True),
                attempt(4, "g-held", "2026-11-06T12:40:00Z"),
                attempt(3, "g-lost", "2026-11-06T12:30:00Z"),
                attempt(2, "g-lost", "2026-11-06T12:20:00Z"),
            ]
        },
    )

    world.pass_()
    world.pass_()

    assert world.api.posts() == ["/app/hook/deliveries/3/attempts"]
    assert "starpulse_github_redeliveries_total 1.0" in world.counted.exposition().decode()


def test_a_merged_pull_request_with_no_inbox_row_is_inserted_once_as_a_reconcile_row(world: World) -> None:
    world.api.serve(PULLS, '"p1"', {"items": [pull(7)]})
    world.api.serve(f"/repos/{REPO}/commits/{HEAD}/check-suites", '"s1"', {"check_suites": []})

    world.pass_()
    world.api.serve(PULLS, '"p2"', {"items": [pull(7, updated="2026-11-06T12:30:00Z")]})
    world.pass_()

    (row,) = world.rows()
    assert (row["delivery_id"], row["source"], row["event"], row["repository"]) == (
        f"reconcile:{REPO}:7:{MERGE}", "reconcile", "pull_request", REPO,
    )  # fmt: skip
    (fact,) = facts_of(row["event"], row["body"])
    assert (fact.event, fact.number, fact.key) == ("PR_MERGED", 7, MERGE)
    assert 'starpulse_github_reconcile_rows_total{kind="pull_request"} 1.0' in world.counted.exposition().decode()


def test_a_finished_check_suite_with_no_inbox_row_is_inserted_for_its_pull_request(world: World) -> None:
    world.api.serve(PULLS, '"p1"', {"items": [pull(8, state="open", merged=False)]})
    world.api.serve(f"/repos/{REPO}/commits/{HEAD}/check-suites", '"s1"', {"check_suites": [suite(555, "failure", 8)]})

    world.pass_()

    (row,) = world.rows()
    assert (row["delivery_id"], row["source"], row["event"]) == (f"reconcile:{REPO}:8:{HEAD}:555", "reconcile", "check_suite")
    (fact,) = facts_of(row["event"], row["body"])
    assert (fact.event, fact.number, fact.key) == ("CHECKS_FAILED", 8, "555")


def test_a_304_leaves_the_cursor_and_the_inbox_unchanged(world: World) -> None:
    world.api.serve(DELIVERIES, '"d1"', {"items": [attempt(2, "g-lost", "2026-11-06T12:20:00Z")]})
    world.api.serve(PULLS, '"p1"', {"items": [pull(7)]})
    world.pass_()
    cursors = (world.cursors.get("deliveries"), world.cursors.get(f"pulls:{REPO}"))
    inbox = world.rows()

    world.pass_()

    assert world.api.gets(DELIVERIES) == [None, '"d1"']
    assert world.api.gets(PULLS) == [None, '"p1"']
    assert (world.cursors.get("deliveries"), world.cursors.get(f"pulls:{REPO}")) == cursors
    assert world.rows() == inbox
    assert world.api.posts() == ["/app/hook/deliveries/2/attempts"]


def test_a_pass_that_cannot_redeliver_keeps_its_cursor_so_the_next_pass_asks_again(world: World) -> None:
    world.api.serve(DELIVERIES, '"d1"', {"items": [attempt(2, "g-lost", "2026-11-06T12:20:00Z")]})
    world.api.post_status = 403

    world.pass_()

    assert world.cursors.get("deliveries") is None

    world.api.post_status = 202
    world.pass_()

    assert world.cursors.get("deliveries") is not None
    assert world.api.posts() == ["/app/hook/deliveries/2/attempts"] * 2


def test_an_organisation_is_reconciled_through_its_unarchived_repositories(world: World) -> None:
    world.api.serve("/orgs/acme/repos?per_page=100", '"o1"', {"items": [{"full_name": "acme/gadgets"}, {"full_name": "acme/old", "archived": True}]})
    world.api.serve("/repos/acme/gadgets/pulls?state=all&sort=updated&direction=desc&per_page=100", '"p1"', {"items": [pull(3)]})
    world.api.serve("/repos/acme/old/pulls?state=all&sort=updated&direction=desc&per_page=100", '"p2"', {"items": [pull(4)]})

    reconcile(world.api, world.inbox, world.cursors, GitHub("SECRET", organisation="acme"), world.counted, lambda: NOW)

    assert [row["delivery_id"] for row in world.rows()] == [f"reconcile:acme/gadgets:3:{MERGE}"]


def test_a_repository_that_fails_does_not_stop_the_rest(world: World) -> None:
    world.api.serve(PULLS, '"p1"', {"items": [pull(7)]})
    broken = "/repos/acme/broken/pulls?state=all&sort=updated&direction=desc&per_page=100"
    world.api.serve(broken, '"b1"', {"items": [{"number": 1}]})  # no updated_at: the read raises

    reconcile(
        world.api, world.inbox, world.cursors, GitHub("SECRET", repositories=("acme/broken", REPO)), world.counted, lambda: NOW
    )

    assert [row["delivery_id"] for row in world.rows()] == [f"reconcile:{REPO}:7:{MERGE}"]


def test_a_page_that_is_all_fresh_is_followed_to_the_next_and_an_older_item_ends_the_read(world: World) -> None:
    second = f"{PULLS}&page=2"
    world.api.routes[PULLS] = ('"p1"', {"items": [pull(9, updated="2026-11-06T12:50:00Z")]})
    world.api.next[PULLS] = second
    world.api.serve(second, '"p2"', {"items": [pull(8, updated="2026-11-06T12:40:00Z"), pull(2, updated="2026-10-01T00:00:00Z")]})

    world.pass_()

    assert [row["delivery_id"] for row in world.rows()] == [f"reconcile:{REPO}:8:{MERGE}", f"reconcile:{REPO}:9:{MERGE}"]


class Stop:
    """A stop event that sets itself after `passes` waits and keeps the interval each wait was asked for."""

    def __init__(self, passes: int) -> None:
        self.passes, self.waited = passes, []

    def is_set(self) -> bool:
        return len(self.waited) >= self.passes

    def wait(self, seconds: float) -> bool:
        self.waited.append(seconds)
        return self.is_set()


def test_the_pass_runs_at_startup_and_after_each_reconcile_interval() -> None:
    ran: list[int] = []
    stop = Stop(2)

    run(lambda: ran.append(len(stop.waited)), stop, 600.0)  # type: ignore[arg-type]

    assert ran == [0, 1]
    assert stop.waited == [600.0, 600.0]


def test_a_failed_pass_is_retried_on_the_next_interval() -> None:
    stop = Stop(2)
    attempts: list[int] = []

    def failing() -> None:
        attempts.append(1)
        raise OSError(json.dumps({"why": "GitHub down"}))

    run(failing, stop, 600.0)  # type: ignore[arg-type]

    assert len(attempts) == 2
