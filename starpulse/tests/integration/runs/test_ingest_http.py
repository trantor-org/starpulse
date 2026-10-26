"""The run events `POST /api/machine-events` takes: who may post them, what reaches the log and what the page draws."""

from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from starpulse.runs.config import Producer
from starpulse.board.board_feed import BoardFeed, follow
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.runs import run_events
from starpulse.runs.cloudevents import SINGLE, CloudEventsIngest
from starpulse.runs.ingest import MAX_BATCH_BODY
from starpulse.runs.ingest import tokens as ingest_tokens
from starpulse.runs.push_runs import PUSHED_INSTANCE, PushRuns
from starpulse.runtime.adapter_kit import serve, url
from starpulse.runtime.config import load
from starpulse.views.page_server import PageServer

TOKENS = {"cron": "cron-secret", "rundeck": "rundeck-secret"}
PRODUCERS = tuple(Producer(name, f"{name.upper()}_TOKEN", machines=(), actors=()) for name in TOKENS)


def run_cloudevent(**attributes: Any) -> dict[str, Any]:
    """A `StepStarted` CloudEvent from `cron` for run `r1` of `nightly`; an attribute overrides it, `None` removes one."""
    event = {
        "specversion": "1.0",
        "id": "e1",
        "source": "cron",
        "type": "StepStarted",
        "subject": "r1",
        "data": {"workflow": "nightly", "status": "running"},
    }
    return {k: v for k, v in (event | attributes).items() if v is not None}


class Stack:
    def __init__(self, server: PageServer, feed: BoardFeed, log: EventLog) -> None:
        self.server, self.feed, self.log = server, feed, log

    def post(
        self, event: Any, token: str | None = None, path: str = "/api/machine-events", content_type: str | None = SINGLE
    ) -> tuple[int, dict]:
        raw = event if isinstance(event, bytes) else json.dumps(event).encode()
        request = urllib.request.Request(url(self.server, path), data=raw, method="POST")
        if content_type is not None:
            request.add_header("Content-Type", content_type)
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return exc.code, json.loads(body) if exc.headers.get_content_type() == "application/json" else {}

    def entries(self) -> list[dict]:
        return [entry.fields for entry in Tail.replay(self.log, run_events.STREAM).poll()]

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
    events = CloudEventsIngest({p.name: p for p in PRODUCERS}, TOKENS, log, {})
    with serve(tmp_path, feed, events=events) as server:
        yield Stack(server, feed, log)
    stop.set()


def test_an_event_posted_with_its_producers_token_shows_in_the_snapshot(stack: Stack) -> None:
    status, answer = stack.post(run_cloudevent(), "cron-secret")

    assert (status, answer) == (201, {"accepted": True})
    dag = stack.until_drawn("pushed/cron/nightly")
    assert (dag["status"], dag["runId"]) == ("running", "r1")


def test_a_step_event_is_written_to_the_log_under_its_producer(stack: Stack) -> None:
    stack.post(
        run_cloudevent(data={"workflow": "nightly", "status": "running", "step": "load", "depends": ["fetch"]}),
        "cron-secret",
    )

    (entry,) = stack.entries()
    assert {key: entry[key] for key in ("event", "workflow", "run_id", "status", "step", "depends", "instance")} == {
        "event": "StepStarted",
        "workflow": "nightly",
        "run_id": "r1",
        "status": "running",
        "step": "load",
        "depends": ["fetch"],
        "instance": "cron",
    }


@pytest.mark.parametrize(
    ("attributes", "status"),
    [
        ({"source": "rundeck"}, 403),
        ({"subject": None}, 400),
        ({"data": None}, 400),
        ({"data": {"workflow": "nightly", "status": "sideways"}}, 400),
        ({"data": {"workflow": "", "status": "running"}}, 400),
        ({"type": "StepPaused"}, 400),
    ],
)
def test_a_run_event_the_contract_refuses_answers_4xx_and_writes_nothing(
    stack: Stack, attributes: dict, status: int
) -> None:
    assert stack.post(run_cloudevent(**attributes), "cron-secret", "/api/machine-events", SINGLE)[0] == status
    assert stack.entries() == []


def test_a_missing_or_wrong_token_answers_401_and_writes_nothing(stack: Stack) -> None:
    assert stack.post(run_cloudevent())[0] == 401
    assert stack.post(run_cloudevent(), "wrong")[0] == 401
    assert stack.post(run_cloudevent(), "cron-secret-")[0] == 401

    assert stack.entries() == []
    assert stack.drawn() == {}


def test_the_same_workflow_name_posted_by_two_producers_stays_two_workflows(stack: Stack) -> None:
    stack.post(run_cloudevent(), "cron-secret")
    failed = run_cloudevent(source="rundeck", subject="d9", data={"workflow": "nightly", "status": "failed"})
    stack.post(failed, "rundeck-secret")

    assert stack.until_drawn("pushed/cron/nightly")["runId"] == "r1"
    assert stack.until_drawn("pushed/rundeck/nightly")["status"] == "failed"


def test_a_body_larger_than_the_limit_answers_413_and_writes_nothing(stack: Stack) -> None:
    # The server answers on the declared length and closes unread, so sending the body would race that close.
    connection = http.client.HTTPConnection("127.0.0.1", stack.server.server_port, timeout=5)
    try:
        connection.putrequest("POST", "/api/machine-events")
        connection.putheader("Authorization", "Bearer cron-secret")
        connection.putheader("Content-Type", SINGLE)
        connection.putheader("Content-Length", str(MAX_BATCH_BODY + 1))
        connection.endheaders()
        status = connection.getresponse().status
    finally:
        connection.close()

    assert status == 413
    assert stack.entries() == []


def test_a_get_answers_405(stack: Stack) -> None:
    request = urllib.request.Request(url(stack.server, "/api/machine-events"))
    with pytest.raises(urllib.error.HTTPError) as got:
        urllib.request.urlopen(request, timeout=5)

    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def test_the_removed_runs_events_route_answers_404_and_writes_nothing(stack: Stack) -> None:
    event = {"event": "StepStarted", "workflow": "cron/nightly", "run_id": "r1", "status": "running"}

    assert stack.post(event, "cron-secret", "/api/runs/events", None)[0] == 404
    assert stack.entries() == []


def test_a_server_with_no_producer_has_no_ingest_route(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    with serve(tmp_path, BoardFeed()) as server:
        status, _ = Stack(server, BoardFeed(), log).post(run_cloudevent(), "cron-secret")

    assert status == 404
    assert Tail.replay(log, run_events.STREAM).poll() == []


def test_a_producer_from_the_documented_config_draws_its_pushed_run_with_no_run_now(tmp_path: Path) -> None:
    config_file = tmp_path / "starpulse.toml"
    config_file.write_text('[[producers]]\nname = "cron"\ntoken_env = "CRON_INGEST_TOKEN"\n')
    config = load(config_file)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(domains=config.qualified_domains(), run_safe=config.qualified_run_safe())
    pushed = PushRuns(feed.runs(PUSHED_INSTANCE), None)
    stop = threading.Event()
    follow(pushed, log, run_events.STREAM, pushed.handle_entry, stop=stop, interval=0.01)
    tokens = ingest_tokens(config.producers, {"CRON_INGEST_TOKEN": "cron-secret"})
    events = CloudEventsIngest({p.name: p for p in config.producers}, tokens, log, {})

    with serve(tmp_path, feed, events=events) as server:
        stack = Stack(server, feed, log)
        status, _ = stack.post(run_cloudevent(subject="2026-10-03"), "cron-secret")
        dag = stack.until_drawn("pushed/cron/nightly")
    stop.set()

    assert (status, dag["status"], dag["runId"]) == (201, "running", "2026-10-03")
    assert not any(d["runSafe"] for domain in feed.snapshot()["domains"] for d in domain["dags"])
