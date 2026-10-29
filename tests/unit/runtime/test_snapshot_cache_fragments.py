"""A BoardFeed.put for one task re-encodes only that task's snapshot fragment."""

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import task
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache

from tests.machines import MACHINES, ROLES


def test_a_move_of_one_task_keeps_unrelated_agent_json_bytes() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    for task_id in ("PROJ-1", "PROJ-2", "PROJ-3"):
        feed.put(task(task_id, "To Do", description=f"About {task_id}"))
    cache = SnapshotCache(feed, ttl_s=60, settle_s=0)
    cache.get()
    before = {
        agent["id"]: kept[1]
        for agent in cache.get().snapshot["flows"][0]["agents"]
        for kept in [cache._tasks[id(agent)]]
    }

    feed.put(task("PROJ-2", "In Progress", description="About PROJ-2"))
    cache.get()
    after = {agent["id"]: cache._tasks[id(agent)][1] for agent in cache.get().snapshot["flows"][0]["agents"]}

    assert after["PROJ-1"] is before["PROJ-1"]
    assert after["PROJ-3"] is before["PROJ-3"]
    assert after["PROJ-2"] is not before["PROJ-2"]
