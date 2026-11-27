"""The intake listener: a signed GitHub delivery is saved to the inbox before it is answered 202.

A delivery the store refuses (a migration holding its write lock) is answered 503 and saved again as soon as the store
takes writes, so its fact reaches the consumers without waiting for the sweeper's reconcile to redeliver it.

`bind` builds the server; `start` is the `github` context `starpulse serve` supervises. It saves to the inbox tables of
the main store and reaches nothing else of it.
"""

import collections
import functools
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from sqlalchemy.engine import Engine

from starpulse.github.adapters.outbound import verdicts as metrics
from starpulse.github.adapters.outbound.inbox import SqlInbox
from starpulse.github.adapters.outbound.queue import Backlog, backlogs
from starpulse.github.model.delivery import UNVERIFIED, Delivery, Refusal, admit, declared_length
from starpulse.github.model.github_config import GitHub
from starpulse.github.ports.inbox import Inbox, InboxError

__all__ = ["bind", "start"]

log = logging.getLogger("starpulse.github")
#: Seconds a request may take to send its declared body, in all and between two reads, before it is dropped.
READ_TIMEOUT = 15
#: Seconds between two saves of a delivery the store refused; a save waiting on a lock returns as soon as it clears.
RETRY_S = 5.0
#: Seconds the oldest refused delivery is saved again before every held one is left to the reconcile redelivery, which
#: runs every 30 minutes, so a delivery the store never takes stops holding up the ones behind it.
GIVE_UP_S = 900.0
#: Refused deliveries held at most; one past it is left to the reconcile redelivery.
HELD_MAX = 1000


class _Refused:
    """The deliveries the store refused, saved again in arrival order by one thread as soon as it takes writes, until
    `stop` is set or the oldest has waited `GIVE_UP_S`. They live in memory only: each was answered 503, so GitHub lists
    it failed and the sweeper's reconcile redelivers whatever this gave up. One thread holds one connection of the
    shared engine however many wait."""

    def __init__(self, inbox: Inbox, stop: threading.Event) -> None:
        self._inbox = inbox
        self._stop = stop
        self._held: collections.deque[Delivery] = collections.deque()
        self._lock = threading.Lock()

    def add(self, delivery: Delivery) -> None:
        with self._lock:
            if len(self._held) >= HELD_MAX:
                log.warning("delivery %s left to the reconcile redelivery: %d already held", delivery.delivery_id, HELD_MAX)
                return
            self._held.append(delivery)
            if len(self._held) == 1:
                threading.Thread(target=self._drain, name="github-intake-resave", daemon=True).start()

    def _drain(self) -> None:
        """Runs while `_held` is not empty, so `add` starts the next thread only once this one is gone: `_saved_all`
        ends it under the lock that saw `_held` empty, and any other end empties `_held` before it returns."""
        try:
            if self._saved_all():
                return
        except Exception:
            log.exception("saving refused deliveries again failed")
        with self._lock:
            log.warning("%d refused deliveries left to the reconcile redelivery", len(self._held))
            self._held.clear()

    def _saved_all(self) -> bool:
        with self._lock:
            delivery = self._held[0]
        since = time.monotonic()
        while True:
            try:
                self._inbox.save(delivery)
            except InboxError:
                if self._stop.wait(RETRY_S) or time.monotonic() - since >= GIVE_UP_S:
                    return False
                continue
            log.info("delivery %s saved after the store refused it", delivery.delivery_id)
            with self._lock:
                self._held.popleft()
                if not self._held:
                    return True
                delivery = self._held[0]
            since = time.monotonic()


def _handler(
    settings: GitHub, secret: bytes, inbox: Inbox, verdicts: metrics.Verdicts, refused: _Refused
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
                log.exception("delivery %s was not saved; saving it again once the store takes writes", delivery.delivery_id)
                verdicts.count(delivery.event, "error")
                refused.add(delivery)
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


class _Held(ThreadingHTTPServer):
    """A listener on a socket `serve` bound and keeps open: closing it ends this process's copy, and a delivery posted
    before the next listener accepts waits in the socket's backlog."""

    def __init__(self, listening: socket.socket, handler: type[BaseHTTPRequestHandler]) -> None:
        self.address_family = listening.family
        super().__init__(listening.getsockname()[:2], handler, bind_and_activate=False)
        self.socket.close()
        self.socket = listening


def bind(
    settings: GitHub,
    secret: bytes,
    inbox: Inbox,
    backlogs: Callable[[], dict[str, Backlog]] | None = None,
    listening: socket.socket | None = None,
    *,
    stop: threading.Event,
) -> ThreadingHTTPServer:
    """The listener on `listening`, else on `settings`' address, signed with `secret` and saving to `inbox`, its
    `/metrics` gauging the backlogs `backlogs` reads. A delivery the inbox refuses is saved again until `stop` is set.
    Raises `OSError` for an address that cannot be bound."""
    refused = _Refused(inbox, stop)
    handler = _handler(settings, secret, inbox, metrics.Verdicts(backlogs), refused)
    if listening is not None:
        return _Held(listening, handler)
    return ThreadingHTTPServer((settings.host, settings.port), handler)


def start(
    config: Any, stop: threading.Event, engine: Engine, listening: socket.socket | None = None
) -> Callable[[], None]:
    """The `github` context: serve `[github]` on threads until `stop` is set, which closes the listener. `engine` opens
    the main store, whose inbox tables it saves to; the store's owner disposes it. `listening` is the socket `serve` holds for it, which outlives this context's replacement.

    Raises `ValueError` without the table or without the secret in the environment, and `OSError` when the address is
    taken, which the `contexts` process retries with a backoff. Returns the context's reload, which has nothing to
    re-read: the table is a restart block."""
    settings: GitHub | None = config.github
    if settings is None:
        raise ValueError("the github context needs a [github] table")
    secret = os.environ.get(settings.secret_env)
    if not secret:
        raise ValueError(f"github: the environment variable {settings.secret_env} holds no webhook secret")
    server = bind(settings, secret.encode(), SqlInbox(engine), functools.partial(backlogs, engine), listening, stop=stop)

    def close() -> None:
        stop.wait()
        server.shutdown()
        server.server_close()

    threading.Thread(target=server.serve_forever, name="github-intake", daemon=True).start()
    threading.Thread(target=close, name="github-intake-close", daemon=True).start()
    return lambda: None
