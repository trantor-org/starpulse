"""The insights API on a running server: an engine posts, re-posts and retracts a finding, the history store keeps each
state, and the stream carries an `insight` event for each."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.client import HTTPResponse
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from starpulse.adapter_kit import next_event, serve, url
from starpulse.board_feed import BoardFeed
from starpulse.contracts.adapters import Finding
from starpulse.ingest import MAX_BODY
from starpulse.insights import Insights, InsightStore, restore
from starpulse.store.tables import insights as insight_table

NOW = 1_700_000_100.0
FINDING = {
    "id": "slow-review",
    "engine": {"name": "skill-coach", "version": "1.4.0"},
    "scope": {"team": "platform", "state": "review"},
    "severity": "warn",
    "text": "Review takes four times as long as the norm.",
    "evidence": [{"label": "time in review", "url": "https://hub.example/history?state=review"}],
    "created_at": 1_700_000_000.0,
}


class Stack:
    def __init__(self, server: ThreadingHTTPServer, feed: BoardFeed, store: InsightStore) -> None:
        self.server, self.feed, self.store = server, feed, store

    def send(self, method: str, path: str, body: Any = None) -> tuple[int, dict]:
        raw = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url(self.server, path), data=raw, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            return exc.code, json.loads(data) if exc.headers.get_content_type() == "application/json" else {}

    def post(self, body: Any = None) -> tuple[int, dict]:
        return self.send("POST", "/api/insights", FINDING if body is None else body)

    def stream(self) -> HTTPResponse:
        """The event stream, past its snapshot."""
        resp = urllib.request.urlopen(url(self.server, "/api/events"), timeout=5)
        assert next_event(resp)[0] == "snapshot"
        return resp

    def rows(self) -> list[Any]:
        with self.store.engine.connect() as db:
            return list(db.execute(select(insight_table)))


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    feed = BoardFeed(clock=lambda: NOW)
    store = InsightStore(f"sqlite:///{tmp_path / 'history.sqlite'}")
    with serve(tmp_path, feed, insights=Insights(store, feed, clock=lambda: NOW)) as server:
        yield Stack(server, feed, store)


def test_a_posted_finding_is_stored_drawn_in_the_snapshot_and_sent_as_an_insight_event(stack: Stack) -> None:
    events = stack.stream()

    assert stack.post() == (201, {"id": "slow-review", "replaced": False})

    name, data = next_event(events)
    assert (name, data["id"], data["finding"]["text"]) == ("insight", "slow-review", FINDING["text"])
    assert Finding.model_validate(data["finding"]) == Finding.model_validate(FINDING)
    assert [f["id"] for f in stack.feed.snapshot()["insights"]] == ["slow-review"]
    assert [f.id for f in stack.store.live(NOW)] == ["slow-review"]


def test_a_re_post_replaces_the_finding_by_its_id_everywhere(stack: Stack) -> None:
    stack.post()
    events = stack.stream()

    status, answer = stack.post({**FINDING, "severity": "act", "text": "Review is now five times the norm."})

    assert (status, answer) == (200, {"id": "slow-review", "replaced": True})
    name, data = next_event(events)
    assert (name, data["finding"]["severity"], data["finding"]["text"]) == (
        "insight",
        "act",
        "Review is now five times the norm.",
    )
    assert [(f["severity"], f["text"]) for f in stack.feed.snapshot()["insights"]] == [
        ("act", "Review is now five times the norm.")
    ]
    assert [r.severity for r in stack.rows()] == ["act"]


def test_a_retracted_finding_leaves_the_page_and_the_live_list_but_stays_in_the_history(stack: Stack) -> None:
    stack.post()
    events = stack.stream()

    assert stack.send("DELETE", "/api/insights/slow-review") == (200, {"id": "slow-review", "retracted": True})

    assert next_event(events) == ("insight", {"id": "slow-review", "finding": None})
    assert stack.feed.snapshot()["insights"] == []
    assert stack.store.live(NOW) == []
    [row] = stack.rows()
    assert (row.id, row.retracted_at) == ("slow-review", NOW)


def test_a_retracted_id_can_be_posted_again(stack: Stack) -> None:
    stack.post()
    stack.send("DELETE", "/api/insights/slow-review")

    assert stack.post() == (201, {"id": "slow-review", "replaced": False})

    assert [f.id for f in stack.store.live(NOW)] == ["slow-review"]
    assert [r.retracted_at for r in stack.rows()] == [None]


def test_retracting_an_id_that_is_not_live_answers_404_and_sends_nothing(stack: Stack) -> None:
    assert stack.send("DELETE", "/api/insights/unknown")[0] == 404
    stack.post()
    stack.send("DELETE", "/api/insights/slow-review")
    events = stack.stream()

    assert stack.send("DELETE", "/api/insights/slow-review")[0] == 404
    stack.post({**FINDING, "id": "next"})
    assert next_event(events)[1]["id"] == "next"


def test_an_id_with_reserved_characters_is_retracted_by_its_decoded_form(stack: Stack) -> None:
    stack.post({**FINDING, "id": "repo/board stuck"})

    assert stack.send("DELETE", "/api/insights/repo%2Fboard%20stuck")[0] == 200
    assert stack.store.live(NOW) == []


@pytest.mark.parametrize("person", ["person", "user", "assignee", "author"])
def test_a_finding_whose_scope_names_a_person_is_refused_and_writes_nothing(stack: Stack, person: str) -> None:
    events = stack.stream()

    status, answer = stack.post({**FINDING, "scope": {"team": "platform", person: "alice"}})

    assert status == 400
    assert f"scope.{person}" in answer["error"]
    assert stack.rows() == [] and stack.feed.snapshot()["insights"] == []
    stack.post({**FINDING, "id": "after"})
    assert next_event(events)[1]["id"] == "after"


def test_a_body_that_is_not_a_finding_is_refused_with_the_field_to_fix(stack: Stack) -> None:
    assert stack.post(b"not json")[0] == 400
    assert stack.post([FINDING])[0] == 400
    status, answer = stack.post({**FINDING, "text": "x" * 281})
    assert (status, "text" in answer["error"]) == (400, True)
    assert stack.rows() == []


def test_a_body_over_the_limit_is_refused_unread(stack: Stack) -> None:
    assert stack.post(b" " * (MAX_BODY + 1))[0] == 413
    assert stack.rows() == []


def test_the_insights_collection_takes_only_a_post(stack: Stack) -> None:
    assert stack.send("GET", "/api/insights")[0] == 405
    assert stack.send("PUT", "/api/insights", FINDING)[0] == 404


def test_an_expired_finding_is_stored_but_not_drawn_or_live(stack: Stack) -> None:
    status, _ = stack.post({**FINDING, "expires_at": NOW - 1})

    assert status == 201
    assert stack.feed.snapshot()["insights"] == [] and stack.store.live(NOW) == []
    assert len(stack.rows()) == 1


def test_a_restarted_hub_draws_the_findings_that_are_still_live(stack: Stack, tmp_path: Path) -> None:
    stack.post()
    stack.post({**FINDING, "id": "gone"})
    stack.send("DELETE", "/api/insights/gone")
    stack.post({**FINDING, "id": "old", "expires_at": NOW - 1})
    restarted = BoardFeed(clock=lambda: NOW)

    restore(InsightStore(stack.store.engine.url.render_as_string(hide_password=False)), restarted)

    assert [f["id"] for f in restarted.snapshot()["insights"]] == ["slow-review"]


def test_a_server_without_the_insights_api_has_no_such_route(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed()) as server:
        stack = Stack(server, BoardFeed(), InsightStore("sqlite://"))

        assert stack.post()[0] == 404
        assert stack.send("DELETE", "/api/insights/slow-review")[0] == 404
