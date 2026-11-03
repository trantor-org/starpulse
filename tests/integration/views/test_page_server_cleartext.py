"""A TLS page server answers cleartext on the same TCP port: the first byte of a connection (a TLS record's 0x16 or
anything else) says which, so `http://` callers keep working beside `https://` and HTTP/3."""

from __future__ import annotations

import http.client
import socket
import ssl
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from starpulse.views.adapters.inbound.page_server import PageServer

from tests.integration.views.test_page_server_tls_shutdown import _Ok

H2_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
         "-keyout", str(key), "-out", str(cert)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    started = PageServer(_Ok(), tls=(cert, key))  # type: ignore[arg-type]
    started.start()
    yield started
    started.close()


def test_cleartext_http11_is_answered_on_the_tls_port(server: PageServer) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request("GET", "/")
    answer = connection.getresponse()

    assert (answer.status, answer.read()) == (200, b"ok")


def test_https_is_still_answered_on_the_same_port(server: PageServer) -> None:
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    connection = http.client.HTTPSConnection("127.0.0.1", server.server_port, timeout=5, context=context)
    connection.request("GET", "/")
    answer = connection.getresponse()

    assert (answer.status, answer.read()) == (200, b"ok")


def test_cleartext_http2_with_prior_knowledge_is_answered_on_the_tls_port(server: PageServer) -> None:
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as raw:
        raw.sendall(H2_PREFACE)
        first = raw.recv(64)  # the server's SETTINGS frame

    assert first[3:4] == b"\x04"  # frame type SETTINGS


def test_a_connection_that_sends_nothing_does_not_hold_up_the_next(server: PageServer) -> None:
    with socket.create_connection(("127.0.0.1", server.server_port)):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", "/")

        assert connection.getresponse().status == 200
