"""`POST /api/pulls/refresh` on the running server: a token-guarded request the PR store's thread serves at once."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.pulls.pull_refresh import PullRefresh
from starpulse._internal.pulls.pull_store import PullSync, refresh_repository
from starpulse._internal.pulls.pulls import PullStore
from starpulse.tests.unit.pulls.test_pull_store import NEW, REPO, Github

TOKEN = "refresh-secret"


class Stack:
    def __init__(self, server: ThreadingHTTPServer, store: PullStore, github: Github) -> None:
        self.server, self.store, self.github = server, store, github

    def post(self, body: object, token: str | None = TOKEN) -> int:
        request = urllib.request.Request(
            url(self.server, "/api/pulls/refresh"),
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def state(self, number: int) -> str:
        return next(pull["state"] for pull in self.store.find(number=number))


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    github = Github()
    github.add(1)
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    refresh_repository(REPO, store, 100.0, github)
    projections = threading.Semaphore(0)
    feed = BoardFeed()
    sync = PullSync(store, feed, (), github, lambda: 160.0, projections.release)
    threading.Thread(target=sync.run_forever, args=(3600.0,), daemon=True).start()
    for _ in range(2):  # the thread projects the saved store, then makes its first refresh; the next is an hour away
        assert projections.acquire(timeout=5)
    github.add(1, state="MERGED", updated=NEW, merged_at=NEW)  # merged on GitHub; the store has not heard
    github.queries.clear()
    with serve(tmp_path, feed, pull_refresh=PullRefresh(TOKEN, sync.request)) as server:
        yield Stack(server, store, github)


def test_a_request_with_the_token_has_the_store_thread_publish_the_merge_without_a_refresh(stack: Stack) -> None:
    assert stack.post({"repo": REPO, "number": 1}) == 202

    deadline = time.monotonic() + 5
    while stack.state(1) != "MERGED":
        assert time.monotonic() < deadline, "the store never learned the merge"
        time.sleep(0.01)
    assert len(stack.github.queries) == 1  # this request's one single-PR read, no listing


def test_a_request_without_the_token_is_refused_and_reads_nothing(stack: Stack) -> None:
    assert stack.post({"repo": REPO, "number": 1}, token=None) == 401
    assert stack.post({"repo": REPO, "number": 1}, token="wrong") == 401

    time.sleep(0.2)
    assert stack.state(1) == "OPEN"
    assert stack.github.queries == []


def test_a_repository_the_instance_does_not_track_is_refused(stack: Stack) -> None:
    assert stack.post({"repo": "evil/other", "number": 1}) == 403
    assert stack.github.queries == []
