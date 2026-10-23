"""Every entry path records a run as History: a run pushed over HTTP or gRPC, and a run an Adapter reports, are one stream
in the event store."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest

from starpulse._internal.config.config import Producer
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.runs.cloudevents import SINGLE, CloudEventsIngest
from starpulse._internal.runs.projection import Publisher
from starpulse._internal.runs.run_history import RunHistory
from starpulse._internal.runs.wire.cloudevents_pb2 import CloudEvent
from starpulse._internal.server.page_server import PageServer
from starpulse._internal.store import EventStore

TOKEN = "cron-secret"
PRODUCERS = {"cron": Producer("cron", "CRON_TOKEN", machines=(), actors=())}


class Stack:
    def __init__(self, server: PageServer, history: RunHistory, log: EventLog) -> None:
        self.server, self.history, self.log = server, history, log

    def post_http(self, id: str, type: str, status: str, step: str | None = None) -> int:
        data = {"workflow": "nightly", "status": status} | ({"step": step} if step else {})
        event = {"specversion": "1.0", "id": id, "source": "cron", "type": type, "subject": "r1", "data": data}
        request = urllib.request.Request(url(self.server, "/api/machine-events"), data=json.dumps(event).encode())
        request.add_header("Content-Type", SINGLE)
        request.add_header("Authorization", f"Bearer {TOKEN}")
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status

    def post_grpc(self, id: str, type: str, status: str, step: str | None = None) -> None:
        data = {"workflow": "nightly", "status": status} | ({"step": step} if step else {})
        event = CloudEvent(id=id, source="cron", spec_version="1.0", type=type, text_data=json.dumps(data))
        event.attributes["subject"].ce_string = "r1"
        address = url(self.server, "/").split("//")[1].rstrip("/")
        with grpc.insecure_channel(address) as channel:
            publish = channel.unary_unary(
                "/starpulse.v1.CloudEventsIngest/Publish",
                request_serializer=CloudEvent.SerializeToString,
                response_deserializer=lambda raw: raw,
            )
            publish(event, metadata=[("authorization", f"Bearer {TOKEN}")], timeout=5)


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    history = RunHistory(EventStore(log.engine))
    events = CloudEventsIngest(PRODUCERS, {"cron": TOKEN}, log, {}, history=history)
    with serve(tmp_path, BoardFeed(), events=events) as server:
        yield Stack(server, history, log)


def test_a_run_pushed_over_http_and_grpc_is_one_stream(stack: Stack) -> None:
    assert stack.post_http("e1", "StepStarted", "running") == 201
    stack.post_grpc("e2", "StepStarted", "running", step="load")
    assert stack.post_http("e3", "StepFinished", "succeeded", step="load") == 201
    stack.post_grpc("e4", "StepFinished", "succeeded")

    record = stack.history.read("cron", "r1")

    assert [(e.version, e.type, e.writer) for e in record.events] == [
        (1, "StepStarted", "ingest"),
        (2, "StepStarted", "ingest"),
        (3, "StepFinished", "ingest"),
        (4, "StepFinished", "ingest"),
    ]
    assert (record.status, record.steps, record.gaps) == ("succeeded", {"load": "succeeded"}, [])


def test_a_push_sent_again_after_a_lost_answer_is_on_the_stream_once(stack: Stack) -> None:
    stack.post_http("e1", "StepStarted", "running")
    stack.post_http("e1", "StepStarted", "running")

    assert len(stack.history.read("cron", "r1").events) == 1


def test_a_push_only_run_that_lost_a_step_end_shows_the_gap(stack: Stack) -> None:
    stack.post_http("e1", "StepStarted", "running")
    stack.post_http("e2", "StepStarted", "running", step="load")  # its StepFinished never arrives
    stack.post_http("e3", "StepFinished", "succeeded")

    assert stack.history.read("cron", "r1").gaps == ["load"]


def test_every_adapter_report_reaches_the_stream_through_the_publisher(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    history = RunHistory(EventStore(log.engine))
    publisher = Publisher(log, history)
    dag = {"name": "etl", "status": "running", "runId": "r9", "steps": [{"name": "load", "status": "running"}]}
    done = {"name": "etl", "status": "succeeded", "runId": "r9", "steps": [{"name": "load", "status": "succeeded"}]}

    for instance in ("dagu", "github"):
        sink = publisher.runs(instance, BoardFeed().runs(instance))
        sink.set_dags([dag], None)
        sink.set_dags([done], None)

    for instance in ("dagu", "github"):
        record = history.read(instance, "r9")
        assert [(e.type, e.writer) for e in record.events] == [("StepStarted", "adapter")] * 2 + [
            ("StepFinished", "adapter")
        ] * 2
        assert (record.status, record.steps) == ("succeeded", {"load": "succeeded"})
