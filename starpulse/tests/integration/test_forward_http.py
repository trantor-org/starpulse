"""`POST /api/forward` on the running server: the hub's route for a forwarder's batches."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse.adapter_kit import serve, url
from starpulse.adapters.runs.ingest import MAX_FORWARD_BODY, ForwardIngest
from starpulse.store import events
from starpulse.store.event_log import EventLog, Tail

EVENT = {
    "event_id": "e1",
    "stream": events.STREAM,
    "fields": {"machine": "board", "event": "MOVED", "task": "T-1", "time": 1.0},
}


class Hub:
    def __init__(self, server: ThreadingHTTPServer, log: EventLog) -> None:
        self.server, self.log = server, log

    def post(self, body: Any, token: str | None = "ana-secret") -> tuple[int, dict]:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(url(self.server, "/api/forward"), data=raw, method="POST")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def stored(self) -> list[str]:
        return [e.event_id for e in Tail(self.log, events.STREAM).poll()]


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[Hub]:
    log = EventLog(f"sqlite:///{tmp_path / 'hub.sqlite'}")
    with serve(tmp_path, forward=ForwardIngest({"ana": "ana-secret"}, log)) as server:
        yield Hub(server, log)


def test_a_batch_posted_with_a_sources_token_is_appended(hub: Hub) -> None:
    status, answer = hub.post({"opt_in": False, "events": [EVENT]})

    assert (status, answer) == (200, {"accepted": 1, "rejected": 0})
    assert hub.stored() == ["ana/e1"]


def test_a_wrong_token_answers_401_and_writes_nothing(hub: Hub) -> None:
    assert hub.post({"opt_in": False, "events": [EVENT]}, "wrong")[0] == 401
    assert hub.post({"opt_in": False, "events": [EVENT]}, None)[0] == 401
    assert hub.stored() == []


def test_a_body_over_the_limit_answers_413_and_writes_nothing(hub: Hub) -> None:
    # The server answers on the declared length and closes unread, so sending the body would race that close.
    connection = http.client.HTTPConnection("127.0.0.1", hub.server.server_port, timeout=5)
    try:
        connection.putrequest("POST", "/api/forward")
        connection.putheader("Authorization", "Bearer ana-secret")
        connection.putheader("Content-Length", str(MAX_FORWARD_BODY + 1))
        connection.endheaders()
        status = connection.getresponse().status
    finally:
        connection.close()

    assert status == 413
    assert hub.stored() == []


def test_a_get_answers_405_with_post_allowed(hub: Hub) -> None:
    with pytest.raises(urllib.error.HTTPError) as got:
        urllib.request.urlopen(url(hub.server, "/api/forward"), timeout=5)

    assert (got.value.code, got.value.headers["Allow"]) == (405, "POST")


def test_a_server_with_no_sources_has_no_forward_route(tmp_path: Path) -> None:
    with serve(tmp_path) as server:
        request = urllib.request.Request(url(server, "/api/forward"), data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as got:
            urllib.request.urlopen(request, timeout=5)

    assert got.value.code == 404
