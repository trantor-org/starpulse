"""The snapshot encoded with each open task's JSON kept between builds."""

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse.contracts.api import encode, encode_snapshot
from starpulse.tests.machines import MACHINES


def _feed(*tasks: tuple[str, str]) -> BoardFeed:
    feed = BoardFeed(machines=MACHINES)
    for task_id, lane in tasks:
        feed.put(task(task_id, lane, description=f"About {task_id}"))
    return feed


def test_the_snapshot_encodes_to_the_bytes_a_full_encode_makes() -> None:
    feed = _feed(("PROJ-1", "To Do"), ("PROJ-2", "In Progress"), ("PROJ-3", "Done"))
    snapshot = feed.snapshot()

    assert encode_snapshot(snapshot, {}) == encode("snapshot", snapshot)


def test_a_snapshot_with_no_open_task_encodes_to_the_bytes_a_full_encode_makes() -> None:
    snapshot = _feed().snapshot()

    assert encode_snapshot(snapshot, {}) == encode("snapshot", snapshot)


def test_a_rebuild_keeps_the_encoding_of_every_task_the_feed_still_holds_unchanged() -> None:
    feed = _feed(("PROJ-1", "To Do"), ("PROJ-2", "To Do"), ("PROJ-3", "To Do"))
    held: dict = {}
    encode_snapshot(feed.snapshot(), held)
    before = {t["id"]: kept[1] for t in feed.snapshot()["flows"][0]["agents"] for kept in [held[id(t)]]}

    feed.put(task("PROJ-2", "In Progress", description="About PROJ-2"))
    feed.put(task("PROJ-4", "To Do", description="About PROJ-4"))
    snapshot = feed.snapshot()
    body = encode_snapshot(snapshot, held)

    after = {t["id"]: held[id(t)][1] for t in snapshot["flows"][0]["agents"]}
    assert body == encode("snapshot", snapshot)
    assert after["PROJ-1"] is before["PROJ-1"]
    assert after["PROJ-3"] is before["PROJ-3"]
    assert after["PROJ-2"] is not before["PROJ-2"]
    assert len(held) == 4


def test_a_task_the_feed_no_longer_holds_is_forgotten() -> None:
    feed = _feed(("PROJ-1", "To Do"), ("PROJ-2", "To Do"))
    held: dict = {}
    encode_snapshot(feed.snapshot(), held)

    feed.retract("PROJ-2")
    encode_snapshot(feed.snapshot(), held)

    assert len(held) == 1


def _with_ledgers(snapshot: dict, **events: list[dict]) -> dict:
    return {**snapshot, "ledgers": events}


def _row(key: str) -> dict:
    return {"key": key, "at": 1.0, "tasks": ["PROJ-1"], "sha": "abc", "runs": {}, "fails": {}, "pinned": False}


def test_a_snapshot_with_ledger_rows_encodes_to_the_bytes_a_full_encode_makes() -> None:
    snapshot = _with_ledgers(_feed(("PROJ-1", "To Do")).snapshot(), MERGED=[_row("a"), _row("b")], REOPEN=[_row("c")])

    assert encode_snapshot(snapshot, {}) == encode("snapshot", snapshot)


def test_a_snapshot_with_ledger_events_but_no_rows_encodes_to_the_bytes_a_full_encode_makes() -> None:
    snapshot = _with_ledgers(_feed(("PROJ-1", "To Do")).snapshot(), MERGED=[], REOPEN=[])

    assert encode_snapshot(snapshot, {}) == encode("snapshot", snapshot)


def test_a_rebuild_keeps_the_encoding_of_each_ledger_row_it_meets_again() -> None:
    first, second = _row("a"), _row("b")
    snapshot = _with_ledgers(_feed(("PROJ-1", "To Do")).snapshot(), MERGED=[first, second])
    held: dict = {}
    encode_snapshot(snapshot, held)
    kept = held[id(first)][1]

    newer = _row("c")
    snapshot = _with_ledgers(snapshot, MERGED=[newer, first], REOPEN=[second])
    body = encode_snapshot(snapshot, held)

    assert body == encode("snapshot", snapshot)
    assert held[id(first)][1] is kept
    assert {id(first), id(second), id(newer)} <= held.keys()
