"""`starpulse.v1.CloudEventsIngest` on the running server: producer-token CloudEvents over gRPC reach the event log."""

from __future__ import annotations

import socket
import struct
from datetime import UTC, datetime
from urllib.parse import urlsplit

import grpc
import h2.connection
import h2.events
import pytest
from google.protobuf.empty_pb2 import Empty
from google.protobuf.timestamp_pb2 import Timestamp

from starpulse._internal.kit.adapter_kit import url
from starpulse.runs.wire.cloudevents_pb2 import CloudEvent, CloudEventBatch
from starpulse.tests.integration.runs import test_cloudevents_http as http
from starpulse.tests.integration.runs.test_cloudevents_http import Stack

SERVICE = "/starpulse.v1.CloudEventsIngest"
stack = http.stack  # the HTTP tests' fixture
TOKEN = ("authorization", "Bearer builder-secret")


def cloudevent(id: str = "e1", **attributes: str) -> CloudEvent:
    """A valid `BUILT` event from `builder` on task `PROJ-1`; an attribute overrides it."""
    event = CloudEvent(id=id, source="builder", spec_version="1.0", type="BUILT")
    stamp = Timestamp()
    stamp.FromDatetime(datetime(2026, 10, 18, 22, tzinfo=UTC))
    event.attributes["time"].ce_timestamp.CopyFrom(stamp)
    for name, value in ({"subject": "PROJ-1", "machine": "delivery", "actor": "ci"} | attributes).items():
        event.attributes[name].ce_string = value
    return event


def address(stack: Stack) -> str:
    return urlsplit(url(stack.server, "/")).netloc


def raw_call(stack: Stack, method: str, message: CloudEvent | CloudEventBatch, token: str | None) -> tuple[dict, dict]:
    """One gRPC call over a bare HTTP/2 connection: the response headers and the trailers, as the server sent them."""
    host, port = address(stack).split(":")
    conn = h2.connection.H2Connection()
    conn.initiate_connection()
    headers = [
        (":method", "POST"),
        (":scheme", "http"),
        (":authority", address(stack)),
        (":path", f"{SERVICE}/{method}"),
        ("content-type", "application/grpc"),
        ("te", "trailers"),
    ]
    if token is not None:
        headers.append(("authorization", f"Bearer {token}"))
    conn.send_headers(1, headers)
    payload = message.SerializeToString()
    conn.send_data(1, b"\x00" + struct.pack(">I", len(payload)) + payload, end_stream=True)
    blocks: list[dict] = []
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(conn.data_to_send())
        done = False
        while not done:
            for event in conn.receive_data(sock.recv(65536)):
                if isinstance(event, h2.events.ResponseReceived | h2.events.TrailersReceived):
                    blocks.append({k.decode(): v.decode() for k, v in event.headers})
                done = done or isinstance(event, h2.events.StreamEnded)
            sock.sendall(conn.data_to_send())
    return blocks[0], blocks[-1]


def unary(stack: Stack, method: str, request_type: type, response_type: type = Empty):
    channel = grpc.insecure_channel(address(stack))
    return channel, channel.unary_unary(
        f"{SERVICE}/{method}",
        request_serializer=request_type.SerializeToString,
        response_deserializer=response_type.FromString,
    )


def test_publish_and_publish_batch_land_in_the_event_log_and_the_status_is_a_trailer(stack: Stack) -> None:
    channel, publish = unary(stack, "Publish", CloudEvent)
    _, publish_batch = unary(stack, "PublishBatch", CloudEventBatch)
    with channel:
        publish(cloudevent("e1"), metadata=[TOKEN], timeout=5)
        publish_batch(
            CloudEventBatch(events=[cloudevent("e2", subject="PROJ-2"), cloudevent("e3", subject="PROJ-3")]),
            metadata=[TOKEN],
            timeout=5,
        )
    head, trailers = raw_call(stack, "Publish", cloudevent("e4"), "builder-secret")

    assert [(e["event_id"], e["task"]) for e in stack.entries()] == [
        ("builder/e1", "PROJ-1"),
        ("builder/e2", "PROJ-2"),
        ("builder/e3", "PROJ-3"),
        ("builder/e4", "PROJ-1"),
    ]
    assert stack.entries()[0]["time"] == datetime(2026, 10, 18, 22, tzinfo=UTC).timestamp()
    assert "grpc-status" not in head
    assert trailers["grpc-status"] == "0"


def test_an_undeclared_event_is_refused_with_a_non_ok_status_in_the_trailers_and_writes_nothing(stack: Stack) -> None:
    channel, publish = unary(stack, "Publish", CloudEvent)
    with channel, pytest.raises(grpc.RpcError) as refused:
        publish(cloudevent("e1", type="LAUNCHED"), metadata=[TOKEN], timeout=5)
    _, trailers = raw_call(stack, "Publish", cloudevent("e2", type="LAUNCHED"), "builder-secret")

    assert refused.value.code() is not grpc.StatusCode.OK
    assert trailers["grpc-status"] != "0"
    assert stack.entries() == []


def test_a_batch_with_one_refused_event_writes_none_of_them(stack: Stack) -> None:
    channel, publish_batch = unary(stack, "PublishBatch", CloudEventBatch)
    with channel, pytest.raises(grpc.RpcError) as refused:
        publish_batch(
            CloudEventBatch(events=[cloudevent("e1"), cloudevent("e2", type="LAUNCHED")]), metadata=[TOKEN], timeout=5
        )

    assert refused.value.code() is not grpc.StatusCode.OK
    assert stack.entries() == []


@pytest.mark.parametrize("token", [None, "wrong"])
def test_a_missing_or_wrong_token_is_unauthenticated(stack: Stack, token: str | None) -> None:
    channel, publish = unary(stack, "Publish", CloudEvent)
    with channel, pytest.raises(grpc.RpcError) as refused:
        publish(cloudevent(), metadata=[] if token is None else [("authorization", f"Bearer {token}")], timeout=5)
    _, trailers = raw_call(stack, "Publish", cloudevent(), token)

    assert refused.value.code() is grpc.StatusCode.UNAUTHENTICATED
    assert trailers["grpc-status"] == str(grpc.StatusCode.UNAUTHENTICATED.value[0])
    assert stack.entries() == []
