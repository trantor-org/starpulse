"""The server of the page: Hypercorn serving `PageApp` on one socket, HTTP/1.1 and HTTP/2 on the same port.

A cleartext port answers HTTP/1.1, and HTTP/2 to a client that opens with its preface (prior knowledge) or asks to
upgrade; a TLS port negotiates `h2` or `http/1.1` through ALPN, and a QUIC socket at the same address answers HTTP/3,
which every TCP response advertises through `alt-svc`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import socket
import threading
from collections.abc import Callable
from pathlib import Path

from hypercorn.asyncio.run import worker_serve
from hypercorn.config import Config, Sockets
from hypercorn.utils import wrap_app

from starpulse._internal.server.asgi_app import PageApp

logger = logging.getLogger(__name__)


#: Connections the kernel queues for the server to accept: a crowd of pages connecting at once fits in it, where the
#: stock 5 drops the rest's SYNs and each waits out a 1 s retransmit before its first byte.
BACKLOG = 128

#: Seconds a client may keep using the `h3` alternative the `alt-svc` header offers before it asks again.
ALT_SVC_MAX_AGE_S = 3600

#: Seconds a stopping server waits for the requests it took, under the 10 s a supervisor allows before it kills a child.
DRAIN_S = 8.0


class PageServer:
    """Serves `app` on its own thread until `stop`.

    Given `listening`, it serves on that socket as passed, its backlog and options untouched, and binds nothing; given
    `tls` (a certificate and its key), it serves TLS on it and HTTP/3 on a UDP socket bound to the same address.
    `stopping`, when set, is called once as the server stops
    and before its streams end, so a page learns the server is restarting before it loses the stream.

    A stopping server ends every open stream, finishes the requests taken (up to `drain_s` seconds) and closes.
    """

    def __init__(
        self,
        app: PageApp,
        address: tuple[str, int] | None = None,
        listening: socket.socket | None = None,
        tls: tuple[Path, Path] | None = None,
        stopping: Callable[[], None] | None = None,
        drain_s: float = DRAIN_S,
    ) -> None:
        self.app, self.stopping, self._drain_s = app, stopping, drain_s
        self.socket = (
            listening if listening is not None else socket.create_server(address or ("127.0.0.1", 0), backlog=BACKLOG)
        )
        self.server_address = self.socket.getsockname()
        self.server_port: int = self.server_address[1]
        self._config = Config()
        self._config.backlog = BACKLOG
        self._config.graceful_timeout = drain_s
        self._config.accesslog = None
        self._config.errorlog = logging.getLogger("hypercorn.error")
        if tls is not None:
            self._config.certfile, self._config.keyfile = str(tls[0]), str(tls[1])
        self._quic: socket.socket | None = None
        if tls is None:
            self._sockets = Sockets([], [self.socket], [])
        else:
            self._quic = socket.socket(self.socket.family, socket.SOCK_DGRAM)
            self._quic.bind(self.server_address)
            self._config.alt_svc_headers = [f'h3=":{self.server_port}"; ma={ALT_SVC_MAX_AGE_S}']
            self._sockets = Sockets([self.socket], [], [self._quic])
        self._stopped = threading.Event()
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run, name="page-server", daemon=True
        )  # its workers are daemons too

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Begin stopping; `join` waits for it to finish."""
        self._stopped.set()
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):  # the loop has already closed
                loop.call_soon_threadsafe(wake.set)

    def drain(self, timeout: float) -> bool:
        """Wait up to `timeout` seconds for every request taken to be answered; whether they all were."""
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(self.app.drained(timeout), self._loop).result()

    def join(self) -> None:
        self._thread.join()
        if self._failure is not None:
            raise self._failure

    def close(self) -> None:
        """Stop, wait for the server to finish and release the socket."""
        self.stop()
        self._thread.join()
        self.socket.close()
        if self._quic is not None:
            self._quic.close()

    def run(self) -> None:
        """Serve until Ctrl-C or `SIGTERM`, then stop."""
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        self.start()
        try:
            while self._thread.is_alive():
                self._thread.join(0.5)
        except KeyboardInterrupt:
            self.stop()
        self.join()

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as failure:
            self._failure = failure

    async def _serve(self) -> None:
        self._wake = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        if self._stopped.is_set():  # `stop` came before the loop did
            self._wake.set()
        await worker_serve(
            wrap_app(self.app, self._config.wsgi_max_body_size, "asgi"),
            self._config,
            sockets=self._sockets,
            shutdown_trigger=self._wait_and_wind_down,
        )

    async def _wait_and_wind_down(self) -> None:
        assert self._wake is not None
        await self._wake.wait()
        if self.stopping is not None:
            await asyncio.to_thread(self.stopping)
        await self.app.end_streams()
        if not await self.app.drained(self._drain_s):
            logger.warning("stopping with requests still running after %.0f s", self._drain_s)
