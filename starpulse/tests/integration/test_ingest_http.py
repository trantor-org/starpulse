"""`POST /api/runs/events` on the running server: a token-guarded push that reaches the page's snapshot."""

from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.runs import run_events
from starpulse._internal.runs.ingest import MAX_BODY, Ingest
from starpulse._internal.runs.ingest import tokens as ingest_tokens
from starpulse._internal.runs.push_runs import PUSHED_INSTANCE, PushRuns
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.feed.board_feed import BoardFeed, follow
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog, Tail

TOKENS = {"cron": "cron-secret", "rundeck": "rundeck-secret"}
EVENT = {"phase": "start", "workflow": "cron/nightly", "run_id": "r1", "status": "running"}


class Stack:
    def __init__(self, server: ThreadingHTTPServer, feed: BoardFeed, log: EventLog) -> None:
        self.server, self.feed, self.log = server, feed, log

    def post(self, event: Any, token: str | None = None, path: str = "/api/runs/events") -> tuple[int, dict]:
        raw = event if isinstance(event, bytes) else json.dumps(event).encode()
        request = urllib.request.Request(url(self.server, path), data=raw, method="POST")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return exc.code, json.loads(body) if exc.headers.get_content_type() == "application/json" else {}

    def entries(self) -> list[dict]:
        return [entry.fields for entry in Tail(self.log, run_events.STREAM).poll()]

    def drawn(self) -> dict[str, dict]:
        return {dag["name"]: dag for dag in self.feed.snapshot()["dags"]}

    def until_drawn(self, name: str) -> dict:
        deadline = time.monotonic() + 5
        while name not in self.drawn():
            assert time.monotonic() < deadline, f"{name} never reached the snapshot"
            time.sleep(0.01)
        return self.drawn()[name]


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed()
    pushed = PushRuns(feed.runs(PUSHED_INSTANCE), None)
    stop = threading.Event()
    follow(pushed, log, run_events.STREAM, pushed.handle_entry, stop=stop, interval=0.01)
    with serve(tmp_path, feed, ingest=Ingest(TOKENS, log)) as server:
        yield Stack(server, feed, log)
    stop.set()


def test_an_event_posted_with_its_instances_token_shows_in_the_snapshot(stack: Stack) -> None:
    status, answer = stack.post(EVENT, "cron-secret")

    assert (status, answer) == (201, {"accepted": True})
    dag = stack.until_drawn("pushed/cron/nightly")
    assert (dag["status"], dag["runId"]) == ("running", "r1")


def test_a_missing_or_wrong_token_answers_401_and_writes_nothing(stack: Stack) -> None:
    assert stack.post(EVENT)[0] == 401
    assert stack.post(EVENT, "wrong")[0] == 401
    assert stack.post(EVENT, "rundeck-secret-")[0] == 401

    assert stack.entries() == []
    assert stack.drawn() == {}


def test_a_token_for_one_instance_cannot_post_another_instances_workflow(stack: Stack) -> None:
    status, _ = stack.post(EVENT | {"workflow": "rundeck/nightly"}, "cron-secret")

    assert status == 403
    assert stack.entries() == []
    assert stack.drawn() == {}


def test_the_same_workflow_name_pushed_by_two_instances_stays_two_workflows(stack: Stack) -> None:
    stack.post(EVENT, "cron-secret")
    stack.post(EVENT | {"workflow": "rundeck/nightly", "run_id": "d9", "status": "failed"}, "rundeck-secret")

    assert stack.until_drawn("pushed/cron/nightly")["runId"] == "r1"
    deadline = time.monotonic() + 5
    while "pushed/rundeck/nightly" not in stack.drawn() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stack.drawn()["pushed/rundeck/nightly"]["status"] == "failed"


def test_a_body_larger_than_the_limit_answers_413_and_writes_nothing(stack: Stack) -> None:
    # The server answers on the declared length and closes unread, so sending the body would race that close.
    connection = http.client.HTTPConnection("127.0.0.1", stack.server.server_port, timeout=5)
    try:
        connection.putrequest("POST", "/api/runs/events")
        connection.putheader("Authorization", "Bearer cron-secret")
        connection.putheader("Content-Length", str(MAX_BODY + 1))
        connection.endheaders()
        status = connection.getresponse().status
    finally:
        connection.close()

    assert status == 413
    assert stack.entries() == []


def test_a_get_answers_405_and_the_route_is_not_the_run_route(stack: Stack) -> None:
    request = urllib.request.Request(url(stack.server, "/api/runs/events"))
    with pytest.raises(urllib.error.HTTPError) as got:
        urllib.request.urlopen(request, timeout=5)

    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def test_a_server_with_no_instance_token_has_no_ingest_route(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    with serve(tmp_path, BoardFeed()) as server:
        status, _ = Stack(server, BoardFeed(), log).post(EVENT, "cron-secret")

    assert status == 404
    assert Tail(log, run_events.STREAM).poll() == []


def test_a_push_only_instance_from_the_readmes_config_draws_its_pushed_run_with_no_run_now(tmp_path: Path) -> None:
    config_file = tmp_path / "starpulse.toml"
    config_file.write_text('[[runs]]\nname = "cron"\ntoken_env = "CRON_INGEST_TOKEN"\n')
    config = load(config_file)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(domains=config.qualified_domains(), run_safe=config.qualified_run_safe())
    pushed = PushRuns(feed.runs(PUSHED_INSTANCE), None)
    stop = threading.Event()
    follow(pushed, log, run_events.STREAM, pushed.handle_entry, stop=stop, interval=0.01)
    tokens = ingest_tokens(config.runs, {"CRON_INGEST_TOKEN": "cron-secret"})

    with serve(tmp_path, feed, ingest=Ingest(tokens, log)) as server:
        stack = Stack(server, feed, log)
        # the README's curl example
        status, _ = stack.post(
            {"phase": "start", "workflow": "cron/nightly", "run_id": "2026-10-03", "status": "running"}, "cron-secret"
        )
        dag = stack.until_drawn("pushed/cron/nightly")
    stop.set()

    assert (status, dag["status"], dag["runId"]) == (201, "running", "2026-10-03")
    assert not any(d["runSafe"] for domain in feed.snapshot()["domains"] for d in domain["dags"])
