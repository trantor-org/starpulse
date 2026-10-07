"""The receiver: OTLP/HTTP JSON logs in, parsed events out, and never a failure that makes the exporter retry."""

from __future__ import annotations

import gzip
import http.client
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from starpulse.adapters.harnesses.otlp import LogEvent, receiver


class Spy:
    def __init__(self, fail: bool = False) -> None:
        self.seen: list[LogEvent] = []
        self.fail = fail

    def ingest(self, events: list[LogEvent]) -> None:
        self.seen.extend(events)
        if self.fail:
            raise RuntimeError("consumer down")


def attr(key: str, value: Any) -> dict[str, Any]:
    wrapped = {"intValue": str(value)} if isinstance(value, int) else {"stringValue": value}
    return {"key": key, "value": wrapped}


PAYLOAD = {
    "resourceLogs": [
        {
            "scopeLogs": [
                {
                    "logRecords": [
                        {
                            "attributes": [
                                attr("event.name", "claude_code.skill_activated"),
                                attr("session.id", "s1"),
                                attr("event.sequence", 1),
                                attr("skill.name", "auditing-docs"),
                            ]
                        }
                    ]
                }
            ]
        }
    ]
}


@pytest.fixture
def served() -> Iterator[tuple[str, Spy]]:
    spy = Spy()
    server = ThreadingHTTPServer(("127.0.0.1", 0), receiver(spy.ingest))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", spy
    server.shutdown()
    server.server_close()


def post(base: str, path: str, body: bytes, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": "application/json", **(headers or {})}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_a_logs_post_is_parsed_and_handed_to_the_consumer(served: tuple[str, Spy]) -> None:
    base, spy = served

    status, body = post(base, "/v1/logs", json.dumps(PAYLOAD).encode())

    assert (status, json.loads(body)) == (200, {})
    assert [(e.kind, e.skill, e.session) for e in spy.seen] == [("skill_activated", "auditing-docs", "s1")]


def test_a_gzipped_body_is_read(served: tuple[str, Spy]) -> None:
    base, spy = served

    status, _ = post(base, "/v1/logs", gzip.compress(json.dumps(PAYLOAD).encode()), {"Content-Encoding": "gzip"})

    assert status == 200
    assert len(spy.seen) == 1


def test_a_body_that_is_not_json_is_refused(served: tuple[str, Spy]) -> None:
    base, spy = served

    status, _ = post(base, "/v1/logs", b"{nope")

    assert status == 400
    assert spy.seen == []


def test_a_protobuf_export_is_refused_by_name(served: tuple[str, Spy]) -> None:
    base, _ = served

    status, body = post(base, "/v1/logs", b"\x0a\x00", {"Content-Type": "application/x-protobuf"})

    assert status == 415
    assert b"json" in body.lower()


def test_another_path_is_not_found(served: tuple[str, Spy]) -> None:
    base, _ = served

    assert post(base, "/v1/traces", b"{}")[0] == 404


def test_health_answers_get(served: tuple[str, Spy]) -> None:
    base, _ = served

    with urllib.request.urlopen(base + "/healthz", timeout=5) as response:
        assert (response.status, response.read()) == (200, b"ok")


def raw(base: str, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    """One request with exactly the headers given: `urllib` adds a Content-Type and a Content-Length of its own."""
    connection = http.client.HTTPConnection(base.removeprefix("http://"), timeout=5)
    try:
        connection.putrequest(method, path)
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        return (
            response.status,
            response.getheader("Content-Type"),
            response.getheader("Content-Length"),
            response.read(),
        )
    finally:
        connection.close()


def test_an_acknowledged_export_is_an_empty_json_object(served: tuple[str, Spy]) -> None:
    base, _ = served
    body = json.dumps(PAYLOAD).encode()

    reply = raw(base, "POST", "/v1/logs", body, {"Content-Type": "application/json", "Content-Length": str(len(body))})

    assert reply == (200, "application/json", "2", b"{}")


def test_health_is_plain_text(served: tuple[str, Spy]) -> None:
    base, _ = served

    assert raw(base, "GET", "/healthz") == (200, "text/plain", "2", b"ok")


def test_an_unknown_path_is_a_json_not_found_for_both_methods(served: tuple[str, Spy]) -> None:
    base, _ = served

    assert raw(base, "GET", "/nope") == (404, "application/json", "2", b"{}")
    assert raw(base, "GET", "/v1/logs") == (404, "application/json", "2", b"{}")
    assert raw(base, "POST", "/healthz", b"{}", {"Content-Type": "application/json", "Content-Length": "2"})[0] == 404


@pytest.mark.parametrize("content_type", ["application/json", "application/json; charset=utf-8"])
def test_a_json_content_type_is_accepted_with_or_without_parameters(served: tuple[str, Spy], content_type: str) -> None:
    base, spy = served
    body = json.dumps(PAYLOAD).encode()

    reply = raw(base, "POST", "/v1/logs", body, {"Content-Type": content_type, "Content-Length": str(len(body))})

    assert reply[0] == 200
    assert len(spy.seen) == 1


@pytest.mark.parametrize("headers", [{}, {"Content-Type": "text/plain"}, {"Content-Type": "application/x-protobuf"}])
def test_a_post_that_does_not_declare_json_is_refused_with_the_fix_named(
    served: tuple[str, Spy], headers: dict[str, str]
) -> None:
    base, spy = served

    status, content_type, _, body = raw(base, "POST", "/v1/logs", b"{}", {**headers, "Content-Length": "2"})

    assert (status, content_type) == (415, "application/json")
    assert json.loads(body) == {"error": 'send OTLP as json: set encoding = "json" on the exporter'}
    assert spy.seen == []


def test_a_post_with_no_length_reads_as_an_empty_body(served: tuple[str, Spy]) -> None:
    base, spy = served

    status, _, _, body = raw(base, "POST", "/v1/logs", None, {"Content-Type": "application/json"})

    assert (status, body) == (400, b"{}")
    assert spy.seen == []


def test_a_body_over_the_size_bound_is_refused_and_one_at_the_bound_is_read(
    served: tuple[str, Spy], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _ = served
    monkeypatch.setattr("starpulse.adapters.harnesses.otlp.MAX_BODY", 8)
    headers = {"Content-Type": "application/json"}

    at_bound = raw(base, "POST", "/v1/logs", b'{"a": 1}', {**headers, "Content-Length": "8"})
    over = raw(base, "POST", "/v1/logs", b'{"a": 12}', {**headers, "Content-Length": "9"})

    assert (at_bound[0], over[0], over[3]) == (200, 413, b"{}")


def test_a_body_that_is_not_gzip_but_says_it_is_is_refused(served: tuple[str, Spy]) -> None:
    base, spy = served

    status, _ = post(base, "/v1/logs", b"not gzip", {"Content-Encoding": "gzip"})

    assert status == 400
    assert spy.seen == []


def test_json_that_is_not_an_object_is_acknowledged_with_nothing_mapped(served: tuple[str, Spy]) -> None:
    base, spy = served

    status, body = post(base, "/v1/logs", b"[1, 2]")

    assert (status, body) == (200, b"{}")
    assert spy.seen == []


def test_a_consumer_that_raises_still_acknowledges_the_export() -> None:
    spy = Spy(fail=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), receiver(spy.ingest))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, _ = post(f"http://127.0.0.1:{server.server_port}", "/v1/logs", json.dumps(PAYLOAD).encode())
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
