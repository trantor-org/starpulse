"""`POST /api/machine-events` on the running server: producer-token CloudEvents reach the event log and SSE."""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.config.config import Producer
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.feed.board_feed import BoardFeed, follow
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse._internal.kit.adapter_kit import next_event, serve, url
from starpulse._internal.machines.machine_definition import load_machine
from starpulse._internal.machines.snapshot import describe
from starpulse._internal.machines.transitions import board_machine
from starpulse._internal.runs.cloudevents import BATCH, MAX_DATA, SINGLE, CloudEventsIngest
from starpulse._internal.runs.ingest import MAX_BATCH_BODY
from starpulse._internal.runs.ingest import tokens as ingest_tokens

DELIVERY = """\
name: delivery
states:
  start: {initial: true}
  built: {}
  shipped: {final: true}
events:
  BUILT:
    - {from: start, to: built}
  SHIPPED:
    - {from: built, to: shipped}
writers:
  BUILT: [{actor: ci, trigger: "the build job"}]
  SHIPPED: [{actor: deployer, trigger: "the deploy job"}]
"""
PRODUCERS = (
    Producer("builder", "BUILDER_TOKEN", machines=("delivery",), actors=("ci", "operator")),
    Producer("shipper", "SHIPPER_TOKEN", machines=("delivery", "other"), actors=("deployer",)),
)
TOKENS = {"BUILDER_TOKEN": "builder-secret", "SHIPPER_TOKEN": "shipper-secret"}


def cloudevent(id: str = "e1", **attributes: Any) -> dict[str, Any]:
    """A valid `BUILT` event from `builder` on task `PROJ-1`; an attribute overrides it, and `None` removes one."""
    event = {
        "specversion": "1.0",
        "id": id,
        "source": "builder",
        "type": "BUILT",
        "subject": "PROJ-1",
        "time": "2026-10-18T22:00:00Z",
        "machine": "delivery",
        "actor": "ci",
    }
    return {k: v for k, v in (event | attributes).items() if v is not None}


class Stack:
    def __init__(self, server: ThreadingHTTPServer, log: EventLog) -> None:
        self.server, self.log = server, log

    def post(self, body: Any, token: str | None = "builder-secret", content_type: str = SINGLE) -> tuple[int, dict]:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(url(self.server, "/api/machine-events"), data=raw, method="POST")
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
        return [entry.fields for entry in Tail(self.log, "machine:events").poll()]


def _feed(tmp_path: Path) -> BoardFeed:
    path = tmp_path / "delivery.yaml"
    path.write_text(DELIVERY)
    return BoardFeed(
        machines={"board": board_machine(("To Do", "Done")), "delivery": describe(load_machine(path).machine)}
    )


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = _feed(tmp_path)
    tasks = MachineTasks(feed)
    stop = threading.Event()
    follow(tasks, log, "machine:events", tasks.handle_entry, stop=stop, interval=0.01)
    events = CloudEventsIngest({p.name: p for p in PRODUCERS}, ingest_tokens(PRODUCERS, TOKENS), log, feed.machines)
    with serve(tmp_path, feed, events=events) as server:
        yield Stack(server, log)
    stop.set()


def test_a_single_event_posted_under_a_producer_token_is_in_the_log_and_on_the_stream(stack: Stack) -> None:
    with urllib.request.urlopen(url(stack.server, "/api/events"), timeout=5) as stream:
        assert next_event(stream)[0] == "snapshot"
        status, answer = stack.post(cloudevent())
        moved = next_event(stream)

    assert (status, answer) == (201, {"accepted": True})
    assert stack.entries() == [
        {
            "event_id": "builder/e1",
            "machine": "delivery",
            "event": "BUILT",
            "task": "PROJ-1",
            "actor": "ci",
            "time": datetime(2026, 10, 18, 22, tzinfo=UTC).timestamp(),
            "source": "builder",
        }
    ]
    assert (moved[0], moved[1]["flow"], moved[1]["id"], moved[1]["agent"]["state"]) == (
        "move",
        "delivery",
        "PROJ-1",
        "built",
    )


def test_an_event_keyed_by_a_run_lands_under_its_run(stack: Stack) -> None:
    shipped = cloudevent(source="shipper", type="SHIPPED", actor="deployer", subject=None, run="r7")

    status, _ = stack.post([shipped], "shipper-secret", BATCH)

    assert (status, [(e["event"], e.get("run"), e.get("task")) for e in stack.entries()]) == (
        201,
        [("SHIPPED", "r7", None)],
    )


def test_a_batch_of_valid_events_is_appended_in_order(stack: Stack) -> None:
    status, _ = stack.post([cloudevent("e1"), cloudevent("e2", subject="PROJ-2")], content_type=BATCH)

    assert status == 201
    assert [e["task"] for e in stack.entries()] == ["PROJ-1", "PROJ-2"]


def test_an_event_posted_twice_is_in_the_log_once(stack: Stack) -> None:
    assert [stack.post(cloudevent())[0], stack.post(cloudevent())[0]] == [201, 201]

    assert len(stack.entries()) == 1


@pytest.mark.parametrize("token", [None, "wrong", "builder-secret-"])
def test_a_missing_or_wrong_token_answers_401_and_writes_nothing(stack: Stack, token: str | None) -> None:
    assert stack.post(cloudevent(), token)[0] == 401
    assert stack.entries() == []


@pytest.mark.parametrize(
    "event",
    [
        {"machine": "board"},  # a machine the producer does not write
        {"actor": "deployer"},  # an actor the producer does not speak as
        {"source": "shipper"},  # another producer's name
    ],
)
def test_a_producer_cannot_write_beyond_its_machines_and_actors_or_as_another_producer(
    stack: Stack, event: dict
) -> None:
    assert stack.post(cloudevent(**event))[0] == 403
    assert stack.entries() == []


@pytest.mark.parametrize(
    "event",
    [
        {"type": "UNDECLARED"},  # an event the machine does not declare
        {"actor": "operator"},  # in the producer's actors, but not a writer of BUILT
        {"subject": None},  # keyed by neither task nor run
        {"run": "r1"},  # keyed by both
        {"specversion": "0.3"},
        {"time": "yesterday"},
        {"data": [1]},  # data is a JSON object
        {"subject": ""},
    ],
)
def test_an_event_the_machine_or_the_format_refuses_answers_400_and_writes_nothing(stack: Stack, event: dict) -> None:
    status, answer = stack.post(cloudevent(**event))

    assert (status, bool(answer.get("error"))) == (400, True)
    assert stack.entries() == []


def test_a_machine_the_server_does_not_draw_answers_400_even_when_the_producer_may_write_it(stack: Stack) -> None:
    status, _ = stack.post(cloudevent(source="shipper", machine="other", actor="deployer"), "shipper-secret")

    assert status == 400
    assert stack.entries() == []


def test_a_batch_with_one_refused_event_writes_none_of_them(stack: Stack) -> None:
    status, _ = stack.post([cloudevent("e1"), cloudevent("e2", type="UNDECLARED")], content_type=BATCH)

    assert status == 400
    assert stack.entries() == []


@pytest.mark.parametrize("content_type", ["text/plain", "application/json"])
def test_a_body_that_is_not_a_cloudevents_content_type_answers_400(stack: Stack, content_type: str) -> None:
    assert stack.post(cloudevent(), content_type=content_type)[0] == 400


def test_a_batch_that_is_not_a_list_and_a_body_that_is_not_json_answer_400(stack: Stack) -> None:
    assert stack.post(cloudevent(), content_type=BATCH)[0] == 400
    assert stack.post(b"{", content_type=SINGLE)[0] == 400


def test_data_over_the_cap_answers_413_and_a_body_over_the_limit_is_refused_unread(stack: Stack) -> None:
    status, _ = stack.post(cloudevent(data={"blob": "x" * MAX_DATA}))
    connection = http.client.HTTPConnection("127.0.0.1", stack.server.server_port, timeout=5)
    try:
        connection.putrequest("POST", "/api/machine-events")
        connection.putheader("Authorization", "Bearer builder-secret")
        connection.putheader("Content-Length", str(MAX_BATCH_BODY + 1))
        connection.endheaders()
        oversized = connection.getresponse().status
    finally:
        connection.close()

    assert (status, oversized) == (413, 413)
    assert stack.entries() == []


def test_data_within_the_cap_travels_with_the_entry(stack: Stack) -> None:
    status, _ = stack.post(cloudevent(data={"sha": "abc"}))

    assert (status, stack.entries()[0]["data"]) == (201, {"sha": "abc"})


def test_an_unreachable_database_answers_503(tmp_path: Path) -> None:
    down = EventLog("sqlite:////nonexistent-dir/events.sqlite")
    feed = _feed(tmp_path)
    events = CloudEventsIngest({p.name: p for p in PRODUCERS}, ingest_tokens(PRODUCERS, TOKENS), down, feed.machines)
    with serve(tmp_path, feed, events=events) as server:
        status, _ = Stack(server, down).post(cloudevent())

    assert status == 503


def test_a_get_answers_405(stack: Stack) -> None:
    with pytest.raises(urllib.error.HTTPError) as got:
        urllib.request.urlopen(url(stack.server, "/api/machine-events"), timeout=5)

    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def test_a_server_with_no_producers_has_no_route(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    with serve(tmp_path, BoardFeed()) as server:
        status, _ = Stack(server, log).post(cloudevent())

    assert status == 404
    assert Tail(log, "machine:events").poll() == []
