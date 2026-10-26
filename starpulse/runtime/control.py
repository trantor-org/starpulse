"""The local control endpoint a running `starpulse serve` offers, and the `starpulse reload` verb that calls it.

The endpoint listens on an ephemeral loopback port and answers `POST /reload` only to a caller that holds its token. The
port and a random token are written to a `<config stem>.control` file (`starpulse.control` for `starpulse.toml`),
readable by its owner alone, that sits beside the config (else `starpulse.control` in the working directory) and is
removed when the supervisor stops. `starpulse reload` reads that file, so it reaches the supervisor started from the same
config, even when another config shares the directory, and finds none when `serve` is not running.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from starpulse.runtime.closure import ReloadError

_LOOPBACK = "127.0.0.1"
_TIMEOUT = 120.0  # a reload reads each closure in a fresh interpreter, then replaces what changed
NOT_RUNNING, FAILED = 1, 2  # `starpulse reload` exit codes; success is 0


class Reloadable(Protocol):
    def reload(self) -> dict[str, Any]: ...

    def reexec(self) -> None: ...


def control_file(config: Path | None) -> Path:
    """Where the supervisor started from `config` publishes its endpoint, and where `starpulse reload` looks."""
    return config.with_suffix(".control") if config else Path.cwd() / "starpulse.control"


class Control:
    """The endpoint of one supervisor: `start` publishes it at `path`, `stop` withdraws it."""

    def __init__(self, path: Path, supervisor: Reloadable) -> None:
        self._path = path
        self._supervisor = supervisor
        self._token = secrets.token_urlsafe(32)
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> None:
        handler = _handler(self._supervisor, self._token)
        self._httpd = ThreadingHTTPServer((_LOOPBACK, 0), handler)
        self._httpd.daemon_threads = True
        threading.Thread(  # `stop` waits out one poll
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, name="starpulse-control", daemon=True
        ).start()
        self._path.unlink(missing_ok=True)
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump({"port": self._httpd.server_address[1], "token": self._token}, file)

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        self._path.unlink(missing_ok=True)


def _handler(supervisor: Reloadable, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._reply(HTTPStatus.UNAUTHORIZED, {"error": "missing or wrong control token"})
            if self.path != "/reload":
                return self._reply(HTTPStatus.NOT_FOUND, {"error": f"no such endpoint: {self.path}"})
            try:
                report = supervisor.reload()
            except ReloadError as exc:
                return self._reply(HTTPStatus.CONFLICT, {"error": str(exc)})
            self._reply(HTTPStatus.OK, report)
            if report["supervisor"] == "re-executed":
                supervisor.reexec()  # after the reply: the caller has its answer before this process is replaced

        def _reply(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main(argv: list[str]) -> int:
    """`starpulse reload`: ask the running supervisor to replace what changed and print what it did (JSON)."""
    parser = argparse.ArgumentParser(
        prog="starpulse reload",
        description="Replace the serve children whose code changed, reload in place those whose config changed, and "
        "re-execute serve when its own code changed. Prints what each did as JSON.",
    )
    parser.add_argument("--config", type=Path, default=None, help="the config serve was started with")
    args = parser.parse_args(argv)
    path = control_file(args.config)
    try:
        endpoint = json.loads(path.read_text())
        request = urllib.request.Request(
            f"http://{_LOOPBACK}:{endpoint['port']}/reload",
            method="POST",
            headers={"Authorization": f"Bearer {endpoint['token']}"},
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            sys.stdout.write(response.read().decode() + "\n")
    except (OSError, ValueError, KeyError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            sys.stderr.write(f"starpulse reload: {json.loads(exc.read().decode()).get('error', exc)}\n")
            return FAILED
        sys.stderr.write(f"starpulse reload: no supervisor is running ({path}: {exc})\n")
        return NOT_RUNNING
    return 0
