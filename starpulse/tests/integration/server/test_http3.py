"""A TLS server also answers HTTP/3 on a QUIC socket at the same port number, and every response it gives over TCP
advertises it through `alt-svc`."""

import asyncio
import http.client
import json
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# aioquic and pylsqpack ship no free-threaded wheels and their sources do not build on 3.14t, so the `python-ft` job installs
# without them; the canary covers HTTP/3 there. `test_serve_tls` imports from this module and skips with it.
pytest.importorskip("aioquic")

from aioquic.asyncio import QuicConnectionProtocol, connect
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import DataReceived, H3Event, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent

from starpulse._internal.feed.board_feed import BoardFeed, follow
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse._internal.kit.adapter_kit import serve
from starpulse._internal.machines.machine_definition import load_machine
from starpulse._internal.machines.snapshot import describe
from starpulse._internal.machines.transitions import board_machine
from starpulse._internal.runs.cloudevents import SINGLE, CloudEventsIngest
from starpulse._internal.runs.ingest import tokens as ingest_tokens
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.tests.integration.runs.test_cloudevents_http import DELIVERY, PRODUCERS, TOKENS, cloudevent
from starpulse.tests.integration.server.test_http2 import _h2_request
from starpulse.tests.machines import MACHINES, ROLES


class _Answer:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.body = b""
        self.ended = asyncio.Event()

    @property
    def status(self) -> int:
        return int(self.headers[":status"])


class _H3Client(QuicConnectionProtocol):
    """One HTTP/3 connection; `request` sends one request on a stream of its own and waits for its whole answer."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._http = H3Connection(self._quic)
        self._answers: dict[int, _Answer] = {}

    def quic_event_received(self, event: QuicEvent) -> None:
        for h3_event in self._http.handle_event(event):
            self._h3_event_received(h3_event)

    def _h3_event_received(self, event: H3Event) -> None:
        if not isinstance(event, HeadersReceived | DataReceived):
            return
        answer = self._answers[event.stream_id]
        if isinstance(event, HeadersReceived):
            answer.headers = {name.decode(): value.decode() for name, value in event.headers}
        else:
            answer.body += event.data
        if event.stream_ended:
            answer.ended.set()

    async def request(
        self, authority: str, method: str, path: str, headers: dict[str, str], body: bytes = b""
    ) -> _Answer:
        stream_id = self._quic.get_next_available_stream_id()
        answer = self._answers[stream_id] = _Answer()
        sent = [(b":method", method.encode()), (b":scheme", b"https"), (b":authority", authority.encode())]
        sent += [(b":path", path.encode())] + [(k.encode(), v.encode()) for k, v in headers.items()]
        if body:  # the write routes size a body from its declared length
            sent.append((b"content-length", str(len(body)).encode()))
        self._http.send_headers(stream_id, sent, end_stream=not body)
        if body:
            self._http.send_data(stream_id, body, end_stream=True)
        self.transmit()
        await asyncio.wait_for(answer.ended.wait(), 5)
        return answer


def _h3(
    certificate: tuple[Path, Path], port: int, method: str, path: str, headers: dict[str, str], body: bytes = b""
) -> _Answer:
    async def exchange() -> _Answer:
        configuration = QuicConfiguration(
            is_client=True, alpn_protocols=H3_ALPN, cafile=str(certificate[0]), idle_timeout=5.0
        )
        async with connect("127.0.0.1", port, configuration=configuration, create_protocol=_H3Client) as client:
            return await client.request(f"127.0.0.1:{port}", method, path, headers, body)  # type: ignore[attr-defined]

    return asyncio.run(exchange())


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
            "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return cert, key


def test_a_quic_socket_on_the_servers_port_answers_an_http3_read(
    tmp_path: Path, certificate: tuple[Path, Path]
) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), tls=certificate) as server:
        answer = _h3(certificate, server.server_port, "GET", "/api/history-window", {})

    assert answer.status == 200
    assert answer.headers["content-type"] == "application/json"
    assert isinstance(json.loads(answer.body), dict)


def test_a_cloudevent_posted_over_http3_reaches_the_event_log(tmp_path: Path, certificate: tuple[Path, Path]) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    (tmp_path / "delivery.yaml").write_text(DELIVERY)
    feed = BoardFeed(
        machines={
            "board": board_machine(("To Do", "Done")),
            "delivery": describe(load_machine(tmp_path / "delivery.yaml").machine),
        }
    )
    tasks, stop = MachineTasks(feed), threading.Event()
    follow(tasks, log, "machine:events", tasks.handle_entry, stop=stop, interval=0.01)
    events = CloudEventsIngest({p.name: p for p in PRODUCERS}, ingest_tokens(PRODUCERS, TOKENS), log, feed.machines)
    sent = {"content-type": SINGLE, "authorization": "Bearer builder-secret"}
    with serve(tmp_path, feed, events=events, tls=certificate) as server:
        answer = _h3(
            certificate, server.server_port, "POST", "/api/machine-events", sent, json.dumps(cloudevent()).encode()
        )
    stop.set()

    assert (answer.status, json.loads(answer.body)) == (201, {"accepted": True})
    assert [entry.fields["event_id"] for entry in Tail.replay(log, "machine:events").poll()] == ["builder/e1"]


@pytest.fixture
def tls_context(certificate: tuple[Path, Path]) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(certificate[0]))
    context.set_alpn_protocols(["h2", "http/1.1"])
    return context


def test_http11_and_http2_answer_on_the_same_port_and_advertise_h3(
    tmp_path: Path, certificate: tuple[Path, Path], tls_context: ssl.SSLContext
) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), tls=certificate) as server:
        port: Any = server.server_port
        tls_context.set_alpn_protocols(["http/1.1"])
        h11 = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=tls_context)
        h11.request("GET", "/")
        h11_answer = h11.getresponse()
        h11_alt_svc, h11_status = h11_answer.getheader("alt-svc"), h11_answer.status
        h11.close()
        tls_context.set_alpn_protocols(["h2", "http/1.1"])
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with tls_context.wrap_socket(raw, server_hostname="127.0.0.1") as connection:
                h2_answer = _h2_request(connection, f"127.0.0.1:{port}", "GET", "/", {})

    assert h11_status == 200
    assert h2_answer.status == 200
    assert h11_alt_svc == f'h3=":{port}"; ma=3600'
    assert h2_answer.headers["alt-svc"] == h11_alt_svc


def test_an_idle_tls_server_stops_without_waiting_out_its_drain(tmp_path: Path, certificate: tuple[Path, Path]) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), tls=certificate):
        stopping = time.monotonic()

    assert time.monotonic() - stopping < 4  # its drain is 8 s
