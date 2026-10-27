"""The server answers by Starlette's own routes: a method a path does not take is its 405, a HEAD is a GET's headers, a
file is the static files' and nothing else answers."""

import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import serve as _serve
from starpulse.runtime.adapter_kit import url as _url
from starpulse.views.page_server import PageServer

from tests.machines import MACHINES, ROLES


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
    with _serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        yield server


def _ask(server: PageServer, path: str, method: str = "GET", headers: dict[str, str] | None = None):
    request = urllib.request.Request(_url(server, path), method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.headers, refused.read()


def test_a_head_of_a_read_is_the_headers_of_its_get_and_no_body(server: PageServer) -> None:
    got = _ask(server, "/api/snapshot")
    head = _ask(server, "/api/snapshot", "HEAD")

    assert head[0] == got[0] == 200
    assert (head[1]["Content-Type"], head[1]["Content-Length"]) == (got[1]["Content-Type"], str(len(got[2])))
    assert head[2] == b""


def test_a_head_of_a_stream_answers_its_headers_and_opens_none(server: PageServer) -> None:
    status, headers, body = _ask(server, "/api/events", "HEAD")

    assert (status, headers["Content-Type"], headers["Cache-Control"], body) == (200, "text/event-stream", "no-store", b"")


def test_a_method_no_route_takes_is_a_405_naming_the_ones_it_does(server: PageServer) -> None:
    status, headers, _ = _ask(server, "/api/snapshot", "PATCH")

    assert status == 405
    assert set(headers["Allow"].split(", ")) == {"GET", "HEAD"}  # in no fixed order


def test_a_path_no_route_takes_is_a_404_not_the_page(server: PageServer) -> None:
    assert _ask(server, "/api/nothing")[0] == 404
    assert _ask(server, "/nothing.js")[0] == 404


def test_a_file_unchanged_since_the_page_last_read_it_is_a_304(tmp_path: Path) -> None:
    with _serve(tmp_path) as server:
        (tmp_path / "static" / "assets" / "index-abc123.js").write_text("export const board = 1;\n")
        etag = _ask(server, "/assets/index-abc123.js")[1]["ETag"]
        again = _ask(server, "/assets/index-abc123.js", headers={"If-None-Match": etag})

    assert (again[0], again[2]) == (304, b"")


def test_a_path_out_of_the_static_directory_is_not_served(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("not for the page")
    with _serve(tmp_path) as server:
        status, _, body = _ask(server, "/..%2Fsecret.txt")

    assert status == 404
    assert b"not for the page" not in body
