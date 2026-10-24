"""How the server serves the snapshot: encoded once per change, never once per request."""

import gzip
import json
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import pytest

from starpulse._internal.board.seam import Written
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import next_event as _next_event
from starpulse._internal.kit.adapter_kit import serve as _serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse._internal.server import snapshot_cache
from starpulse._internal.server.page_server import PageServer
from starpulse.contracts.adapters import Move
from starpulse.tests.fake_board import bare_board
from starpulse.tests.machines import MACHINES, ROLES


def _get(server: PageServer) -> bytes:
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


def test_the_snapshot_leaves_a_tasks_detail_out_and_its_full_view_keeps_it(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", description="About it", moves={"in_progress": Move(allowed=True)}))

    with _serve(tmp_path, feed) as server:
        slim = json.loads(_get(server))["flows"][0]["agents"][0]
        with urllib.request.urlopen(_url(server, "/api/snapshot?view=full"), timeout=5) as resp:
            full = json.load(resp)["flows"][0]["agents"][0]

    assert "description" not in slim and "moves" not in slim and "move_set" in slim
    assert full["description"] == "About it"
    assert full["moves"]["in_progress"]["allowed"] is True


def test_the_full_view_sends_a_pull_request_without_the_fields_the_feed_keeps_for_itself(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1"))
    pull = {
        "number": 7,
        "repo": "o/r",
        "url": "https://github.com/o/r/pull/7",
        "checks": "pass",
        "merged": False,
        "merge_sha": None,
        "merged_at": None,
        "files": ["a.py"],
        "threads": 0,
        "behind_main": 0,
        "stale": False,
    }
    feed.set_pulls({"PROJ-1": [pull]})

    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/snapshot?view=full"), timeout=5) as resp:
            sent = json.load(resp)["pulls"]["PROJ-1"][0]

    assert sent["number"] == 7
    assert "files" not in sent


def test_a_snapshot_is_built_once_however_many_pages_ask(tmp_path: Path, builds: Counter[int]) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    with _serve(tmp_path, feed) as server:
        started = builds[id(feed)]
        first = _get(server)
        feed.put(task("PROJ-1", "In Progress"))
        second = _get(server)
        deadline = time.monotonic() + 5
        while b'"in_progress"' not in second and time.monotonic() < deadline:  # the rebuild lands behind the change
            time.sleep(0.05)
            second = _get(server)

    assert b'"to_do"' in first
    assert b'"in_progress"' in second
    assert builds[id(feed)] - started >= 1


def test_a_connecting_page_neither_misses_nor_repeats_a_change(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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


def test_a_page_connecting_during_a_rebuild_is_not_held_up_by_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    release = threading.Event()
    building = threading.Event()
    real = snapshot_cache.encode_snapshot
    stalled = False

    def slow(data: dict, held: dict) -> bytes:
        if stalled:
            building.set()
            release.wait(10)
        return real(data, held)

    monkeypatch.setattr(snapshot_cache, "encode_snapshot", slow)
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
        elif line.startswith("data: ") and name != "build":  # the page build each connect names, not a change
            return name, line.removeprefix("data: ").rstrip("\n")
    raise AssertionError("the stream ended")


def test_a_page_that_asks_for_the_snapshot_by_reference_reads_the_same_snapshot_from_its_body_route(
    tmp_path: Path,
) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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
    with _serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(_url(server, "/api/events/body/" + "0" * 40), timeout=5)
    assert refused.value.code == 404


def test_a_snapshot_is_gzipped_when_built_not_by_the_request_that_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", title="x" * 100_000))  # over the size gzip is worth; a description is no longer sent
    compressions: list[int] = []
    real = gzip.compress

    def counting(data: bytes, *args: object, **kwargs: object) -> bytes:
        # a cache an earlier test in this process left running rebuilds on its own timer; only this feed's task counts
        if b"x" * 100_000 in data:
            compressions.append(len(data))
        return real(data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gzip, "compress", counting)
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events?snapshot=ref"), timeout=5) as resp:
            _, ref = _raw_event(resp)  # a page connecting builds the snapshot and reads none of it
        built = len(compressions)
        gzipped = urllib.request.Request(_url(server, "/api/snapshot"), headers={"Accept-Encoding": "gzip"})
        body = urllib.request.Request(_url(server, ref.removeprefix("ref ")), headers={"Accept-Encoding": "gzip"})
        for request in (gzipped, gzipped, body):
            with urllib.request.urlopen(request, timeout=5) as resp:
                assert resp.headers["Content-Encoding"] == "gzip"

    assert built == 1
    assert len(compressions) == built


def test_a_snapshot_read_straight_after_a_write_holds_the_write(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "Ready", moves={"in_progress": Move(allowed=True)}))

    def writer(name: str, status: str, actor: str) -> Written:
        feed.put(task(name, status, title="written"))
        return Written(True, "ok")

    with _serve(tmp_path, feed, bare_board(writer=writer)) as server:
        before = _get(server)
        move = urllib.request.Request(
            _url(server, "/api/move"),
            data=json.dumps({"task": "PROJ-1", "to": "in_progress", "actor": "operator"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(move, timeout=5).close()
        after = _get(server)

    assert b'"written"' not in before
    assert b'"written"' in after


def test_a_snapshot_change_with_pull_files_is_sent_and_the_stream_stays_open(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1"))
    pull = {
        "number": 7,
        "repo": "o/r",
        "url": "https://github.com/o/r/pull/7",
        "checks": "pass",
        "merged": False,
        "merge_sha": None,
        "merged_at": None,
        "files": ["a.py"],
        "threads": 0,
        "behind_main": 0,
        "stale": False,
    }
    feed.set_pulls({"PROJ-1": [pull]})

    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            assert _next_event(resp)[0] == "snapshot"
            feed.set_window(1000)
            name, data = _next_event(resp)
            assert name == "snapshot"
            assert "files" not in data["pulls"]["PROJ-1"][0]
            feed.put(task("PROJ-2"))
            assert _next_event(resp)[0] == "task"
