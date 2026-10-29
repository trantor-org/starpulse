"""The listen backlog: a crowd of pages connecting at once is queued for accept, not dropped into a SYN retransmit."""

import socket

from starpulse.views.adapters.inbound.page_server import PageServer


def test_fifty_pages_connecting_before_any_is_accepted_all_connect() -> None:
    server = PageServer(None, ("127.0.0.1", 0))  # type: ignore[arg-type] # never started: nothing is accepted
    pages = []
    try:
        for _ in range(50):
            pages.append(socket.create_connection(("127.0.0.1", server.server_port), timeout=0.5))
    finally:
        for page in pages:
            page.close()
        server.socket.close()

    assert len(pages) == 50
