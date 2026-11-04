"""The intake listener: a signed GitHub delivery is saved to the inbox before it is answered 202.

`bind` builds the server; `start` is the `github` context `starpulse serve` supervises. Only the webhook secret and the
inbox are reached from here: never the event store, the page or a producer token.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from starpulse.event_log.wake import StopEvent
from starpulse.github.adapters.outbound import verdicts as metrics
from starpulse.github.adapters.outbound.inbox import Migrate, SqlInbox
from starpulse.github.model.delivery import UNVERIFIED, Delivery, Refusal, admit, declared_length
from starpulse.github.model.github_config import GitHub
from starpulse.github.ports.inbox import Inbox, InboxError

__all__ = ["bind", "start"]

log = logging.getLogger("starpulse.github")
INBOX_FILE = "github.sqlite"
#: Seconds a request may take to send its declared body, in all and between two reads, before it is dropped.
READ_TIMEOUT = 15


def _handler(
    settings: GitHub, secret: bytes, inbox: Inbox, verdicts: metrics.Verdicts
) -> type[BaseHTTPRequestHandler]:
    class Intake(BaseHTTPRequestHandler):
        #: A client that declares a body and stops sending it frees its thread when the read times out.
        timeout = READ_TIMEOUT

        def do_GET(self) -> None:
            if self.path != "/metrics":
                return self._reply(404)
            body = verdicts.exposition()
            self.send_response(200)
            self.send_header("Content-Type", metrics.CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = self.headers.get("Content-Length")
            try:
                outcome = declared_length(settings, length) or admit(
                    settings, secret, self.headers.get, self._body(int(length or 0))
                )
            except TimeoutError:
                verdicts.count(UNVERIFIED, "timeout")
                return self._reply(408)
            if isinstance(outcome, Refusal):
                verdicts.count(outcome.event, outcome.verdict)
                return self._reply(outcome.status)
            self._reply(self._save(outcome))

        def _body(self, length: int) -> bytes:
            """`length` bytes, or `TimeoutError` when they take over `READ_TIMEOUT` seconds in all: a drip of bytes
            that each beat the socket timeout would otherwise hold the thread."""
            deadline = time.monotonic() + READ_TIMEOUT
            chunks: list[bytes] = []
            while length > 0:
                if time.monotonic() > deadline:
                    raise TimeoutError
                chunk = self.rfile.read1(min(length, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                length -= len(chunk)
            return b"".join(chunks)

        def _save(self, delivery: Delivery) -> int:
            try:
                saved = inbox.save(delivery)
            except InboxError:
                log.exception("delivery %s was not saved", delivery.delivery_id)
                verdicts.count(delivery.event, "error")
                return 503
            verdicts.count(delivery.event, "accepted" if saved else "duplicate")
            return 202

        def _reply(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's signature
            """Requests are counted at `/metrics`, not logged."""

    return Intake


def bind(settings: GitHub, secret: bytes, inbox: Inbox) -> ThreadingHTTPServer:
    """The listener on `settings`' address, signed with `secret` and saving to `inbox`. Raises `OSError` for an address that
    cannot be bound."""
    return ThreadingHTTPServer((settings.host, settings.port), _handler(settings, secret, inbox, metrics.Verdicts()))


def start(config: Any, base: Path, stop: StopEvent, migrate: Migrate) -> Callable[[], None]:
    """The `github` context: serve `[github]` on threads until `stop` is set, which closes the listener. `migrate` builds the
    inbox's schema.

    Raises `ValueError` without the table or without the secret in the environment, and `OSError` when the address is
    taken, which the `contexts` process retries with a backoff. Returns the context's reload, which has nothing to
    re-read: the table is a restart block."""
    settings: GitHub | None = config.github
    if settings is None:
        raise ValueError("the github context needs a [github] table")
    secret = os.environ.get(settings.secret_env)
    if not secret:
        raise ValueError(f"github: the environment variable {settings.secret_env} holds no webhook secret")
    inbox = SqlInbox(settings.database_url or f"sqlite:///{(base / INBOX_FILE).resolve()}", migrate)
    try:
        server = bind(settings, secret.encode(), inbox)
    except OSError:
        inbox.engine.dispose()  # the `contexts` process retries `start`, which opens a new inbox
        raise

    def close() -> None:
        stop.wait()
        server.shutdown()
        server.server_close()
        inbox.engine.dispose()

    threading.Thread(target=server.serve_forever, name="github-intake", daemon=True).start()
    threading.Thread(target=close, name="github-intake-close", daemon=True).start()
    return lambda: None
