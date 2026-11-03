"""One listening TCP socket shared by a TLS server and a cleartext one, split by each connection's first byte.

Hypercorn serves a socket as TLS or as cleartext, never both. `ProtocolSplit` accepts on the real socket, reads (without
consuming) the first byte a client sends (0x16 opens every TLS record, a cleartext HTTP/1.1 request or HTTP/2 preface
opens with an ASCII letter) and queues the connection on a `Handoff`: a stand-in listening socket that Hypercorn's
`asyncio.start_server` accepts from like any other, so each side keeps its own handling and the peer's address.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import socket

logger = logging.getLogger(__name__)

#: The first byte of a TLS record of type handshake: a ClientHello.
TLS_HANDSHAKE = 0x16

#: Seconds a connection may stay silent before it is closed. A client speaks first in HTTP/1.1, HTTP/2 and TLS alike.
FIRST_BYTE_TIMEOUT_S = 10.0

#: Seconds accepting pauses after the process runs out of descriptors, as asyncio's own accept loop does.
ACCEPT_PAUSE_S = 1.0


class Handoff(socket.socket):
    """A listening socket whose `accept` returns the connections `deliver` queued, for `asyncio.start_server(sock=)`.

    Its descriptor is one end of a socket pair that holds a byte per queued connection, which is what makes the event
    loop's selector call `accept`.
    """

    def __init__(self, address: tuple[str, int]) -> None:
        bell, self._ring = socket.socketpair()
        super().__init__(fileno=bell.detach())
        self._address = address
        self._queued: collections.deque[tuple[socket.socket, object]] = collections.deque()

    def deliver(self, connection: socket.socket, peer: object) -> None:
        self._queued.append((connection, peer))
        self._ring.send(b"\0")

    def listen(self, backlog: int = 0) -> None:
        """The real socket already listens."""

    def getsockname(self) -> tuple[str, int]:  # type: ignore[override]
        return self._address

    def accept(self) -> tuple[socket.socket, object]:  # type: ignore[override]
        self.recv(1)  # raises BlockingIOError once the queue is empty, which ends asyncio's accept loop
        return self._queued.popleft()

    def close(self) -> None:
        while self._queued:
            self._queued.popleft()[0].close()
        self._ring.close()
        super().close()


class ProtocolSplit:
    """Accepts on `listening` and hands each connection to `tls` or `cleartext` by its first byte."""

    def __init__(self, listening: socket.socket, backlog: int) -> None:
        self.listening, self.backlog = listening, backlog
        address = listening.getsockname()
        self.tls, self.cleartext = Handoff(address), Handoff(address)
        self._routing: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        """Begin accepting on the running event loop."""
        self.listening.setblocking(False)
        self.listening.listen(self.backlog)
        asyncio.get_running_loop().add_reader(self.listening.fileno(), self._accept)

    def stop(self) -> None:
        """Stop accepting and close the connections that have not yet sent their first byte."""
        asyncio.get_running_loop().remove_reader(self.listening.fileno())
        for task in self._routing:
            task.cancel()

    def _accept(self) -> None:
        loop = asyncio.get_running_loop()
        for _ in range(self.backlog):
            try:
                connection, peer = self.listening.accept()
            except (BlockingIOError, InterruptedError):
                return
            except ConnectionAbortedError:
                continue
            except OSError:
                logger.exception("accept failed; pausing %.0f s", ACCEPT_PAUSE_S)
                loop.remove_reader(self.listening.fileno())
                loop.call_later(ACCEPT_PAUSE_S, loop.add_reader, self.listening.fileno(), self._accept)
                return
            connection.setblocking(False)
            task = loop.create_task(self._route(connection, peer))
            self._routing.add(task)
            task.add_done_callback(self._routing.discard)

    async def _route(self, connection: socket.socket, peer: object) -> None:
        try:
            first = await asyncio.wait_for(self._first_byte(connection), FIRST_BYTE_TIMEOUT_S)
        except (TimeoutError, OSError):
            first = b""
        except asyncio.CancelledError:
            connection.close()
            raise
        if not first:
            connection.close()
            return
        (self.tls if first[0] == TLS_HANDSHAKE else self.cleartext).deliver(connection, peer)

    @staticmethod
    async def _first_byte(connection: socket.socket) -> bytes:
        loop = asyncio.get_running_loop()
        readable = loop.create_future()
        loop.add_reader(connection.fileno(), lambda: readable.done() or readable.set_result(None))
        try:
            await readable
        finally:
            loop.remove_reader(connection.fileno())
        return connection.recv(1, socket.MSG_PEEK)
