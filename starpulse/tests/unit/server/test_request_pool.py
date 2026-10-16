"""The request pool: a worker is started only when none is idle, and an idle worker exits after `idle_timeout`.

On free-threaded 3.14t each live thread keeps its allocator heap's high-water pages, so the pool's thread count is
the server's resident memory.
"""

import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from typing import Any

from starpulse._internal.server.server import StarPulseServer


class _Recording(StarPulseServer):
    idle_timeout = 0.2

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.served_by: list[int] = []
        self.release = threading.Event()
        self.release.set()

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        self.release.wait()
        self.served_by.append(threading.get_ident())


def _until(condition: Callable[[], bool], within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _alive(idents: list[int]) -> set[int]:
    return {thread.ident for thread in threading.enumerate()} & set(idents)


def test_sequential_requests_are_served_by_one_worker() -> None:
    server = _Recording()
    try:
        for n in range(20):
            server.process_request(object(), ("127.0.0.1", n))
            assert _until(lambda: len(server.served_by) == n + 1)
            time.sleep(0.02)  # the worker is back waiting for work before the next request arrives
    finally:
        server.server_close()

    assert len(set(server.served_by)) == 1


def test_concurrent_requests_start_one_worker_each() -> None:
    server = _Recording()
    server.release.clear()
    try:
        for n in range(4):
            server.process_request(object(), ("127.0.0.1", n))
        server.release.set()
        assert _until(lambda: len(server.served_by) == 4)
    finally:
        server.server_close()

    assert len(set(server.served_by)) == 4


def test_idle_workers_exit_after_the_timeout() -> None:
    server = _Recording()
    server.release.clear()
    try:
        for n in range(3):
            server.process_request(object(), ("127.0.0.1", n))
        assert server._workers == 3
        server.release.set()
        assert _until(lambda: len(server.served_by) == 3)
        assert _until(lambda: server._workers == 0)
        assert _until(lambda: not _alive(server.served_by))
        server.process_request(object(), ("127.0.0.1", 9))  # a request after they all retired is still served
        assert _until(lambda: len(server.served_by) == 4)
    finally:
        server.server_close()
