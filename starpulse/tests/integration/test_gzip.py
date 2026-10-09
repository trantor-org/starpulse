"""Gzip on the wire: a JSON body over 64 KB and every stream event, only for a page that accepts it."""

import gzip
import json
import urllib.request
import zlib
from http.client import HTTPResponse
from http.server import ThreadingHTTPServer
from pathlib import Path

from starpulse._internal.api.adapter_kit import serve as _serve
from starpulse._internal.api.adapter_kit import task
from starpulse._internal.api.adapter_kit import url as _url
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse.tests.machines import MACHINES

GZIP = {"Accept-Encoding": "gzip"}


def _large_feed() -> BoardFeed:
    """A board whose snapshot is well over 64 KB."""
    feed = BoardFeed(machines=MACHINES)
    for n in range(400):
        feed.put(task(f"PROJ-{n}", title=f"{'a long title ' * 20}{n}"))
    return feed


def _get(server: ThreadingHTTPServer, path: str, headers: dict[str, str]) -> tuple[str | None, bytes]:
    with urllib.request.urlopen(urllib.request.Request(_url(server, path), headers=headers), timeout=5) as resp:
        return resp.headers["Content-Encoding"], resp.read()


class _Decoded:
    """A gzip event stream read as bytes arrive: each `next` returns once its event has been inflated, not at the end."""

    def __init__(self, resp: HTTPResponse) -> None:
        self.resp = resp
        self.inflater = zlib.decompressobj(wbits=31)
        self.pending = b""

    def next(self) -> tuple[str, dict]:
        while True:
            frame, found, rest = self.pending.partition(b"\n\n")
            if found:
                self.pending = rest
                if not frame.startswith(b": ping"):
                    name, _, data = frame.decode().partition("\ndata: ")
                    return name.removeprefix("event: "), json.loads(data)
                continue
            chunk = self.resp.read1(65536)
            assert chunk, "the stream ended"
            self.pending += self.inflater.decompress(chunk)


def test_a_snapshot_over_64_kb_is_gzipped_for_a_page_that_accepts_gzip(tmp_path: Path) -> None:
    with _serve(tmp_path, _large_feed()) as server:
        encoding, compressed = _get(server, "/api/snapshot", GZIP)
        plain_encoding, plain = _get(server, "/api/snapshot", {})

    assert encoding == "gzip"
    assert plain_encoding is None
    assert len(plain) > 64 * 1024
    assert json.loads(gzip.decompress(compressed))["flows"] == json.loads(plain)["flows"]
    assert len(compressed) < len(plain) // 3


def test_a_body_under_64_kb_is_not_compressed_even_for_a_page_that_accepts_gzip(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1"))
    with _serve(tmp_path, feed) as server:
        encoding, body = _get(server, "/api/snapshot", GZIP)

    assert encoding is None
    assert json.loads(body)["flows"][0]["agents"][0]["id"] == "PROJ-1"


def test_a_page_that_refuses_gzip_gets_the_plain_body(tmp_path: Path) -> None:
    with _serve(tmp_path, _large_feed()) as server:
        encoding, body = _get(server, "/api/snapshot", {"Accept-Encoding": "gzip;q=0, identity"})

    assert encoding is None
    assert json.loads(body)["flows"]


def test_each_stream_event_is_decodable_as_it_arrives_for_a_page_that_accepts_gzip(tmp_path: Path) -> None:
    feed = _large_feed()
    with _serve(tmp_path, feed) as server:
        request = urllib.request.Request(_url(server, "/api/events"), headers=GZIP)
        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.headers["Content-Encoding"] == "gzip"
            events = _Decoded(resp)
            name, snapshot = events.next()
            feed.put(task("PROJ-NEW", "In Progress"))  # the stream stays open; this event must arrive on its own
            delta_name, delta = events.next()

    assert name == "snapshot"
    assert len(snapshot["flows"][0]["agents"]) == 400
    assert (delta_name, delta["id"]) == ("task", "PROJ-NEW")


def test_the_stream_is_plain_for_a_page_that_does_not_accept_gzip(tmp_path: Path) -> None:
    with _serve(tmp_path, _large_feed()) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            encoding, first = resp.headers["Content-Encoding"], resp.readline()

    assert encoding is None
    assert first == b"event: snapshot\n"


def _snapshot_ref(server: ThreadingHTTPServer) -> str:
    """The body route a page that asks for the snapshot by reference reads it from."""
    with urllib.request.urlopen(_url(server, "/api/events?snapshot=ref"), timeout=5) as resp:
        frame = resp.readline() + resp.readline()
    return frame.decode().partition("data: ref ")[2].strip()


def test_the_snapshot_body_a_page_reads_by_reference_is_gzipped_for_a_page_that_accepts_gzip(tmp_path: Path) -> None:
    with _serve(tmp_path, _large_feed()) as server:
        ref = _snapshot_ref(server)
        encoding, compressed = _get(server, ref, GZIP)
        plain_encoding, plain = _get(server, ref, {})

    assert (encoding, plain_encoding) == ("gzip", None)
    assert gzip.decompress(compressed) == plain
    assert len(compressed) < len(plain) // 3


def test_a_hashed_asset_is_gzipped_and_kept_for_a_year(tmp_path: Path) -> None:
    script = "export const board = 'a long line of the bundle';\n" * 400
    with _serve(tmp_path) as server:
        (tmp_path / "static" / "assets" / "index-abc123.js").write_text(script)
        with urllib.request.urlopen(
            urllib.request.Request(_url(server, "/assets/index-abc123.js"), headers=GZIP)
        ) as resp:
            zipped, body, kind = resp.headers, resp.read(), resp.headers["Content-Type"]
        with urllib.request.urlopen(_url(server, "/assets/index-abc123.js")) as resp:
            plain, plain_body = resp.headers, resp.read()

    assert (zipped["Content-Encoding"], kind) == ("gzip", "text/javascript")
    assert gzip.decompress(body).decode() == script == plain_body.decode()
    assert plain["Content-Encoding"] is None
    assert zipped["Cache-Control"] == plain["Cache-Control"] == "public, max-age=31536000, immutable"


def test_the_page_itself_is_not_kept(tmp_path: Path) -> None:
    with _serve(tmp_path) as server, urllib.request.urlopen(_url(server, "/")) as resp:
        assert resp.headers["Cache-Control"] is None


def test_the_snapshot_is_gzipped_once_however_many_pages_read_it(tmp_path: Path, monkeypatch) -> None:
    calls = []
    real = gzip.compress
    monkeypatch.setattr(gzip, "compress", lambda *a, **k: calls.append(1) or real(*a, **k))
    with _serve(tmp_path, _large_feed()) as server:
        ref = _snapshot_ref(server)
        bodies = {_get(server, path, GZIP)[1] for path in ["/api/snapshot", ref] * 3}

    assert len(bodies) == 1
    assert len(calls) == 1
