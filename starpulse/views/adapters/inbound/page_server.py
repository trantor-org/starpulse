"""The server of the page: Hypercorn serving `PageApp` on one socket, HTTP/1.1 and HTTP/2 on the same port.

A cleartext port answers HTTP/1.1, and HTTP/2 to a client that opens with its preface (prior knowledge) or asks to
upgrade; a TLS port negotiates `h2` or `http/1.1` through ALPN, and a QUIC socket at the same address answers HTTP/3,
which every TCP response advertises through `alt-svc`.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import signal
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hypercorn.asyncio.run import worker_serve
from hypercorn.config import Config, Sockets
from hypercorn.utils import wrap_app

from starpulse.views.adapters.inbound.asgi_app import PageApp

logger = logging.getLogger(__name__)


#: Connections the kernel queues for the server to accept: a crowd of pages connecting at once fits in it, where the
#: stock 5 drops the rest's SYNs and each waits out a 1 s retransmit before its first byte.
BACKLOG = 128

#: The backlog a socket handed in keeps: `starpulse.socket`'s `Backlog=1024`. Hypercorn calls `listen` with its config's
#: backlog on every socket it serves, so a handed socket gets this number, not `BACKLOG`, or the unit's queue shrinks to 128.
INHERITED_BACKLOG = 1024

#: Seconds a client may keep using the `h3` alternative the `alt-svc` header offers before it asks again.
ALT_SVC_MAX_AGE_S = 3600

#: Seconds between the datagrams a stopping server sends its QUIC socket so Hypercorn's QUIC loop sees the stop.
NUDGE_S = 0.05

#: Seconds a stopping server waits for the requests it took, under the 10 s a supervisor allows before it kills a child.
DRAIN_S = 8.0


def _survive_cancelled_streams() -> None:
    """Make Hypercorn's HTTP/3 `stream_send` drop an event for a stream the client cancelled, once per process.

    A browser closing a tab sends RESET_STREAM and STOP_SENDING, after which aioquic refuses every write to the stream
    (`ValueError`, `RuntimeError`, `FrameUnexpected`). The refusal reaches the app's `send`, and `_handle`'s `finally`
    then runs `send(None)`, which answers a stream still in its request state with a 500 through the same `stream_send`
    and raises again outside the `try`. That second error leaves Hypercorn's `TaskGroup`, which cancels
    `UDPServer.run`; `worker_serve` never awaits that task, so the QUIC socket stays bound and answers nothing."""
    from aioquic.h3.connection import FrameUnexpected  # noqa: PLC0415
    from hypercorn.protocol.h3 import H3Protocol  # noqa: PLC0415

    send = H3Protocol.stream_send
    if getattr(send, "drops_cancelled_streams", False):
        return

    async def stream_send(self: H3Protocol, event: Any) -> None:
        try:
            await send(self, event)
        except (FrameUnexpected, RuntimeError, ValueError) as refused:
            logger.info("dropped %s for a cancelled HTTP/3 stream: %s", type(event).__name__, refused)

    stream_send.drops_cancelled_streams = True  # type: ignore[attr-defined]
    H3Protocol.stream_send = stream_send  # type: ignore[method-assign]


class PageServer:
    """Serves `app` on its own thread until `stop`.

    Given `listening`, it serves on that socket with backlog `INHERITED_BACKLOG`, and binds nothing; given
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
        for key, file in zip(("tls_cert", "tls_key"), tls or (), strict=False):
            if not file.is_file():
                raise FileNotFoundError(f"{key} {file} does not exist")
        self.app, self.stopping, self._drain_s = app, stopping, drain_s
        self.socket = (
            listening if listening is not None else socket.create_server(address or ("127.0.0.1", 0), backlog=BACKLOG)
        )
        # asyncio sets TCP_NODELAY on a connection only when its listener's protocol is TCP, and `socket.create_server`
        # leaves it 0: without this each response's body waits out the client's 40 ms delayed ACK behind its head.
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.server_address = self.socket.getsockname()
        self.server_port: int = self.server_address[1]
        self._config = Config()
        self._config.backlog = BACKLOG if listening is None else INHERITED_BACKLOG
        self._config.graceful_timeout = drain_s
        self._config.accesslog = None
        self._config.errorlog = logging.getLogger("hypercorn.error")
        if tls is not None:
            self._config.certfile, self._config.keyfile = str(tls[0]), str(tls[1])
        self._quic: socket.socket | None = None
        if tls is None:
            self._sockets = Sockets([], [self.socket], [])
        elif importlib.util.find_spec("aioquic") is None:
            # The free-threaded build installs no aioquic: its TLS port serves h2 and http/1.1 and advertises no `h3`.
            self._sockets = Sockets([self.socket], [], [])
        else:
            self._quic = socket.socket(self.socket.family, socket.SOCK_DGRAM)
            self._quic.bind(self.server_address)
            self._config.alt_svc_headers = [f'h3=":{self.server_port}"; ma={ALT_SVC_MAX_AGE_S}']
            _survive_cancelled_streams()
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
        nudger = asyncio.create_task(self._nudge_quic())
        try:
            await worker_serve(
                wrap_app(self.app, self._config.wsgi_max_body_size, "asgi"),
                self._config,
                sockets=self._sockets,
                shutdown_trigger=self._wait_and_wind_down,
            )
        finally:
            nudger.cancel()

    async def _nudge_quic(self) -> None:
        """Once stopping, send the QUIC socket a datagram Hypercorn drops: its QUIC loop checks for the stop only as a
        datagram arrives, so an idle one would keep the server up for the whole drain."""
        if self._quic is None:
            return
        assert self._wake is not None
        await self._wake.wait()
        with socket.socket(self._quic.family, socket.SOCK_DGRAM) as nudge:
            while True:
                nudge.sendto(b"", self.server_address)
                await asyncio.sleep(NUDGE_S)

    async def _wait_and_wind_down(self) -> None:
        assert self._wake is not None
        await self._wake.wait()
        if self.stopping is not None:
            await asyncio.to_thread(self.stopping)
        await self.app.end_streams()
        if not await self.app.drained(self._drain_s):
            logger.warning("stopping with requests still running after %.0f s", self._drain_s)
