"""`starpulse serve` with a certificate and key in its config answers HTTP/1.1, HTTP/2 and HTTP/3 on one port; without
them it stays cleartext and advertises no HTTP/3."""

import http.client
import socket
import ssl
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from starpulse.tests.integration.server.test_http2 import _h2_request
from starpulse.tests.integration.server.test_http3 import _h3, certificate  # noqa: F401 - `certificate` is a fixture
from starpulse.tests.integration.server.test_standalone import _env, _free_port, _serve_command, build  # noqa: F401 - `build` is a fixture

ALT_SVC = 'h3=":{port}"; ma=3600'


@contextmanager
def _serving(tmp_path: Path, config_text: str) -> Iterator[int]:
    """A `starpulse serve` child on a free port, started from a config file holding `config_text`."""
    config = tmp_path / "starpulse.toml"
    config.write_text(config_text)
    (tmp_path / "empty-path").mkdir()  # no docker, podman or gh resolves
    port = _free_port()
    proc = subprocess.Popen(_serve_command(port, config), env=_env(PATH=str(tmp_path / "empty-path")))
    try:
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def _await_answer(port: int, context: ssl.SSLContext | None) -> http.client.HTTPResponse:
    """The page's answer to `GET /`, retried while the server starts."""
    deadline = time.monotonic() + 60
    while True:
        connection: http.client.HTTPConnection = (
            http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            if context is None
            else http.client.HTTPSConnection("127.0.0.1", port, timeout=2, context=context)
        )
        try:
            connection.request("GET", "/")
            answer = connection.getresponse()
            answer.read()
            return answer
        except OSError:
            assert time.monotonic() < deadline, "the page never answered"
            time.sleep(0.2)


# Stays slow: a real `starpulse serve` child cold-imports the server (~2.3 s) and boots to its first answer (~4 s)
@pytest.mark.slow
@pytest.mark.usefixtures("build")
def test_serve_with_a_certificate_answers_http11_http2_and_http3_on_one_port(
    tmp_path: Path, certificate: tuple[Path, Path]
) -> None:
    cert, key = certificate
    context = ssl.create_default_context(cafile=str(cert))
    context.set_alpn_protocols(["http/1.1"])
    with _serving(tmp_path, f'tls_cert = "{cert}"\ntls_key = "{key}"\n') as port:
        h11 = _await_answer(port, context)
        context.set_alpn_protocols(["h2", "http/1.1"])
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname="127.0.0.1") as connection:
                h2 = _h2_request(connection, f"127.0.0.1:{port}", "GET", "/", {})
        h3 = _h3(certificate, port, "GET", "/", {})

    assert (h11.status, h2.status, h3.status) == (200, 200, 200)
    assert h11.getheader("alt-svc") == ALT_SVC.format(port=port)


@pytest.mark.usefixtures("build")
def test_serve_without_a_certificate_stays_cleartext_with_no_alt_svc(tmp_path: Path) -> None:
    with _serving(tmp_path, "") as port:
        answer = _await_answer(port, None)

    assert (answer.status, answer.getheader("alt-svc")) == (200, None)
