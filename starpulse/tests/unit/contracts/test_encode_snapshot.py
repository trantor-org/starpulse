"""The snapshot encoded with each open task's JSON kept between builds."""

import json

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.server.encoding import encode, encode_snapshot, slim_snapshot
from starpulse.tests.machines import MACHINES, ROLES


def _feed(*tasks: tuple[str, str]) -> BoardFeed:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    for task_id, lane in tasks:
        feed.put(task(task_id, lane, description=f"About {task_id}"))
    return feed


def test_an_in_progress_card_keeps_its_description_and_criteria_and_another_card_leaves_them_out() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(
        task(
            "PROJ-1",
            "In Progress",
            description="About PROJ-1",
            acceptance_criteria=("Checks it",),
            acceptance_checked=(False,),
        )
    )
    feed.put(
        task(
            "PROJ-2",
            "To Do",
            description="About PROJ-2",
            acceptance_criteria=("Checks it",),
            acceptance_checked=(False,),
        )
    )

    body = json.loads(encode_snapshot(feed.snapshot(), {}))
    cards = {card["id"]: card for card in body["flows"][0]["agents"]}

    assert cards["PROJ-1"]["description"] == "About PROJ-1"
    assert cards["PROJ-1"]["criteria"] == [{"text": "Checks it", "checked": False}]
    assert "description" not in cards["PROJ-2"] and "criteria" not in cards["PROJ-2"]


def test_the_snapshot_encodes_to_the_bytes_the_slimmed_encode_makes() -> None:
    feed = _feed(("PROJ-1", "To Do"), ("PROJ-2", "In Progress"), ("PROJ-3", "Done"))
    snapshot = feed.snapshot()

    assert encode_snapshot(snapshot, {}) == encode("snapshot", slim_snapshot(snapshot))


def test_a_snapshot_with_no_open_task_encodes_to_the_bytes_the_slimmed_encode_makes() -> None:
    snapshot = _feed().snapshot()

    assert encode_snapshot(snapshot, {}) == encode("snapshot", slim_snapshot(snapshot))


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
    assert body == encode("snapshot", slim_snapshot(snapshot))
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
