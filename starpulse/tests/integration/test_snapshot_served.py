"""How the server serves the snapshot: encoded once per change, never once per request."""

import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse._internal.feed import snapshot_cache
from starpulse._internal.api.adapter_kit import next_event as _next_event
from starpulse._internal.api.adapter_kit import serve as _serve
from starpulse._internal.api.adapter_kit import task
from starpulse._internal.api.adapter_kit import url as _url
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse.tests.machines import MACHINES


def _get(server: ThreadingHTTPServer) -> bytes:
    with urllib.request.urlopen(_url(server, "/api/snapshot"), timeout=5) as resp:
        return resp.read()


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> Counter[int]:
    """How many snapshots each feed built, by `id(feed)`: a refresher thread another test left running adds to its own
    feed's count, never to this test's."""
    built: Counter[int] = Counter()
    real = BoardFeed.snapshot

    def counting(self: BoardFeed) -> dict:
        built[id(self)] += 1
        return real(self)

    monkeypatch.setattr(BoardFeed, "snapshot", counting)
    return built


def test_a_snapshot_is_built_once_however_many_pages_ask(tmp_path: Path, builds: Counter[int]) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1"))
    with _serve(tmp_path, feed) as server:
        started = builds[id(feed)]  # serving the window built one
        bodies = {_get(server) for _ in range(5)}
        for _ in range(3):
            with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
                _next_event(resp)

    assert len(bodies) == 1
    assert builds[id(feed)] - started == 1


def test_a_change_is_in_the_next_snapshot_served(tmp_path: Path, builds: Counter[int]) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    with _serve(tmp_path, feed) as server:
        started = builds[id(feed)]
        first = _get(server)
        feed.put(task("PROJ-1", "In Progress"))
        second = _get(server)

    assert b'"to_do"' in first
    assert b'"in_progress"' in second
    assert builds[id(feed)] - started == 2


def test_a_connecting_page_neither_misses_nor_repeats_a_change(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-0"))
    seen: set[str] = set()
    repeats: list[str] = []
    stop = threading.Event()

    def writer() -> None:
        n = 0
        while not stop.is_set():
            n += 1
            feed.put(task(f"PROJ-{n}"))
            time.sleep(0.002)

    with _serve(tmp_path, feed) as server:
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
                name, snapshot = _next_event(resp)
                assert name == "snapshot"
                in_snapshot = {a["id"] for a in snapshot["flows"][0]["agents"]}
                for _ in range(40):
                    name, delta = _next_event(resp)
                    assert name == "task"
                    if delta["id"] in seen:
                        repeats.append(delta["id"])
                    seen.add(delta["id"])
        finally:
            stop.set()
            thread.join()

    # a task is drawn from the snapshot or from a delta, and a delta never repeats one the snapshot held
    assert not repeats
    assert not seen & in_snapshot
    # and none between the snapshot and the first delta went missing: the ids are consecutive
    numbers = sorted(int(i.removeprefix("PROJ-")) for i in seen)
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))
    assert max(int(i.removeprefix("PROJ-")) for i in in_snapshot) + 1 == numbers[0]


def test_a_page_connecting_during_a_rebuild_is_not_held_up_by_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    release = threading.Event()
    building = threading.Event()
    real = snapshot_cache.encode
    stalled = False

    def slow(kind: str, data: dict) -> bytes:
        if stalled:
            building.set()
            release.wait(10)
        return real(kind, data)

    monkeypatch.setattr(snapshot_cache, "encode", slow)
    with _serve(tmp_path, feed) as server:
        _get(server)  # held, current
        stalled = True
        feed.put(task("PROJ-1", "In Progress"))  # the rebuild this starts stalls in its encode
        assert building.wait(5)
        try:
            with urllib.request.urlopen(_url(server, "/api/events"), timeout=2) as resp:
                first = _next_event(resp)
                second = _next_event(resp)
        finally:
            release.set()

    # the held snapshot, then the change it lacks, which the page applies on top
    assert first[0] == "snapshot"
    assert [(a["id"], a["state"]) for a in first[1]["flows"][0]["agents"]] == [("PROJ-1", "to_do")]
    assert (second[0], second[1]["id"], second[1]["agent"]["state"]) == ("task", "PROJ-1", "in_progress")


def _raw_event(resp) -> tuple[str, str]:
    """The next named event on the stream with its data as sent, skipping keep-alive comments."""
    name = ""
    while line := resp.readline().decode():
        if line.startswith("event: "):
            name = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            return name, line.removeprefix("data: ").rstrip("\n")
    raise AssertionError("the stream ended")


def test_a_page_that_asks_for_the_snapshot_by_reference_reads_the_same_snapshot_from_its_body_route(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            inline = _raw_event(resp)
        with urllib.request.urlopen(_url(server, "/api/events?snapshot=ref"), timeout=5) as resp:
            name, ref = _raw_event(resp)
            assert name == "snapshot"
            assert ref.startswith("ref /api/events/body/")
            with urllib.request.urlopen(_url(server, ref.removeprefix("ref ")), timeout=5) as body:
                read, kind, cache = body.read().decode(), body.headers["Content-Type"], body.headers["Cache-Control"]
            feed.put(task("PROJ-2"))
            after = _next_event(resp)

    # the body is the snapshot the stream would have sent inline, and the stream goes on with the changes after it
    assert (inline[0], read) == ("snapshot", inline[1])
    assert (kind, cache) == ("application/json", "max-age=3600, immutable")
    assert (after[0], after[1]["id"]) == ("task", "PROJ-2")


def test_a_snapshot_body_the_server_does_not_hold_is_not_found(tmp_path: Path) -> None:
    with _serve(tmp_path, BoardFeed(machines=MACHINES)) as server:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(_url(server, "/api/events/body/" + "0" * 40), timeout=5)
    assert refused.value.code == 404
