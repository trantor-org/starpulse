"""The server answers HTTP/2: on a cleartext port a client that knows it speaks h2 (prior knowledge), and on a TLS port
a client that offers `h2` in ALPN."""

import json
import socket
import ssl
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, ResponseReceived, StreamEnded
from h2.exceptions import ProtocolError
from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import serve

from tests.machines import MACHINES, ROLES


class _Answer:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.body = b""

    @property
    def status(self) -> int | None:
        return int(self.headers[":status"]) if ":status" in self.headers else None


def _h2_request(
    connection: socket.socket, authority: str, method: str, path: str, headers: dict[str, str], body: bytes = b""
) -> _Answer:
    """One request on stream 1 of an HTTP/2 connection the client opens with its preface; the answer's status is None
    when the peer does not speak HTTP/2."""
    h2 = H2Connection(config=H2Configuration(client_side=True))
    h2.initiate_connection()
    request = {":method": method, ":path": path, ":scheme": "http", ":authority": authority, **headers}
    h2.send_headers(1, list(request.items()), end_stream=not body)
    if body:
        h2.send_data(1, body, end_stream=True)
    connection.sendall(h2.data_to_send())
    answer, ended = _Answer(), False
    try:
        while not ended and (received := connection.recv(65535)):
            for event in h2.receive_data(received):
                if isinstance(event, ResponseReceived):
                    answer.headers = {name.decode(): value.decode() for name, value in event.headers}
                elif isinstance(event, DataReceived):
                    answer.body += event.data
                    h2.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                elif isinstance(event, StreamEnded):
                    ended = True
            connection.sendall(h2.data_to_send())
    except ProtocolError, ConnectionError:
        pass
    return answer


@pytest.fixture
def cleartext(tmp_path: Path) -> Iterator[int]:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        yield server.server_port


def _h2c(port: int, method: str, path: str, headers: dict[str, str], body: bytes = b"") -> _Answer:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        return _h2_request(connection, f"127.0.0.1:{port}", method, path, headers, body)


def test_a_client_that_knows_the_port_speaks_http2_gets_the_page(cleartext: int) -> None:
    answer = _h2c(cleartext, "GET", "/", {})

    assert answer.status == 200
    assert answer.headers["content-type"] == "text/html; charset=utf-8"
    assert answer.body == b"<!doctype html>"


def test_an_api_read_over_http2_answers_json(cleartext: int) -> None:
    answer = _h2c(cleartext, "GET", "/api/history-window", {})

    assert answer.status == 200
    assert answer.headers["content-type"] == "application/json"
    assert isinstance(json.loads(answer.body), dict)


def test_a_write_over_http2_is_judged_by_the_authority_it_was_sent_to(cleartext: int) -> None:
    sent = {"content-type": "application/json"}
    same_origin = _h2c(cleartext, "POST", "/api/move", {**sent, "origin": f"http://127.0.0.1:{cleartext}"}, b"{}")
    other_origin = _h2c(cleartext, "POST", "/api/move", {**sent, "origin": "http://evil.example"}, b"{}")

    assert other_origin.status == 403
    assert same_origin.status not in (None, 403, 415)


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost"]
        + ["-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)],
        check=True,
        capture_output=True,
    )
    return cert, key


def test_a_tls_client_offering_h2_in_alpn_is_negotiated_to_http2(
    tmp_path: Path, certificate: tuple[Path, Path]
) -> None:
    context = ssl.create_default_context(cafile=str(certificate[0]))
    context.set_alpn_protocols(["h2", "http/1.1"])
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), tls=certificate) as server:
        port: Any = server.server_port
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname="127.0.0.1") as connection:
                negotiated = connection.selected_alpn_protocol()
                answer = _h2_request(connection, f"127.0.0.1:{port}", "GET", "/", {})

    assert negotiated == "h2"
    assert answer.status == 200
