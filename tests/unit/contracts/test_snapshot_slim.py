"""The snapshot a page is sent: task detail left to /api/task/<id>, each distinct move set once, only the day's settled."""

import json
import time

from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import Move
from starpulse.runtime.adapter_kit import task
from starpulse.views.model.encoding import encode, encode_snapshot, event, slim_snapshot

from tests.machines import MACHINES, ROLES

DAY_S = 86400.0

DAY = 86400.0
NOW = 10_000_000.0
OPEN = {"in_progress": Move(allowed=True)}
GUARDED = {"in_progress": Move(allowed=False, reason="needs a plan", skill="starting-tasks")}


def _midnight() -> float:
    now = time.localtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))


def _feed() -> BoardFeed:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    for n in range(1, 4):
        feed.put(task(f"PROJ-{n}", "To Do", description=f"About PROJ-{n} " + "x" * 400, moves=OPEN))
    feed.put(task("PROJ-4", "To Do", description="Guarded", moves=GUARDED))
    feed.put(task("PROJ-5", "To Do", description="No moves"))
    today = _midnight() + 60
    feed.put(task("PROJ-6", "Done", settled="completed", settled_at=today, created_at=today, milestone="m-1"))
    feed.put(
        task("PROJ-7", "Done", settled="completed", settled_at=today, created_at=today - 30 * DAY, milestone="m-1")
    )
    feed.put(
        task(
            "PROJ-8",
            "Done",
            settled="completed",
            settled_at=today - 30 * DAY,
            created_at=today - 31 * DAY,
            milestone="m-1",
        )
    )
    feed.put(
        task(
            "PROJ-9",
            "Done",
            settled="archived",
            settled_at=today - 30 * DAY,
            created_at=today - 31 * DAY,
            milestone="m-2",
        )
    )
    feed.put(task("PROJ-10", "Done", settled="completed", settled_at=today - 30 * DAY, created_at=today - 31 * DAY))
    return feed


def _sent(feed: BoardFeed) -> dict:
    return json.loads(encode_snapshot(feed.snapshot(), {}))


def test_snapshot_slim_leaves_a_flow_agents_description_and_criteria_to_the_task_record() -> None:
    agents = _sent(_feed())["flows"][0]["agents"]

    assert len(agents) == 5
    assert all("description" not in a and "criteria" not in a for a in agents)


def test_snapshot_slim_encodes_definition_of_done_and_keeps_it_only_on_an_in_progress_task() -> None:
    feed = _feed()
    feed.put(task("PROJ-11", "In Progress", moves=OPEN))
    data = feed.snapshot()
    done = [{"text": "Docs reconciled", "checked": False}]
    agents = [{**agent, "definition_of_done": done} for agent in data["flows"][0]["agents"]]
    data = {**data, "flows": [{**data["flows"][0], "agents": agents}, *data["flows"][1:]]}

    sent = {a["id"]: a for a in json.loads(encode_snapshot(data, {}))["flows"][0]["agents"]}

    assert sent["PROJ-11"]["definition_of_done"] == done
    assert "definition_of_done" not in sent["PROJ-1"]


def test_snapshot_slim_carries_only_open_and_under_24h_done_tasks_and_never_the_cold_ids() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES, clock=lambda: NOW)
    feed.expect("0-0")
    feed.put(task("PROJ-1", "To Do"))
    feed.put(task("PROJ-2", "Done", observed_at=NOW - 60))
    feed.put(task("PROJ-3", "Done", observed_at=NOW - 2 * DAY_S))

    sent = _sent(feed)

    assert [a["id"] for a in sent["flows"][0]["agents"]] == ["PROJ-1", "PROJ-2"]
    assert "cold_done" not in sent and feed.snapshot()["cold_done"] == ["PROJ-3"]


def test_snapshot_slim_names_each_agents_move_set_in_a_table_that_holds_each_distinct_one_once() -> None:
    sent = _sent(_feed())
    agents = {a["id"]: a for a in sent["flows"][0]["agents"]}

    assert all("moves" not in a for a in agents.values())
    assert len(sent["move_sets"]) == 2
    assert agents["PROJ-1"]["move_set"] == agents["PROJ-2"]["move_set"] == agents["PROJ-3"]["move_set"]
    assert agents["PROJ-4"]["move_set"] != agents["PROJ-1"]["move_set"]
    assert "move_set" not in agents["PROJ-5"]
    assert sent["move_sets"][agents["PROJ-1"]["move_set"]]["in_progress"]["allowed"] is True
    assert sent["move_sets"][agents["PROJ-4"]["move_set"]]["in_progress"]["reason"] == "needs a plan"


def test_snapshot_slim_keeps_only_the_tasks_created_or_settled_since_the_day_before_local_midnight() -> None:
    sent = _sent(_feed())

    assert sorted(sent["settled"]) == ["PROJ-6", "PROJ-7"]


def test_snapshot_slim_counts_every_completed_task_by_milestone_however_long_ago_it_settled() -> None:
    assert _sent(_feed())["milestone_done"] == {"m-1": 3}


def test_snapshot_slim_adds_the_read_models_older_done_counts_to_the_settled_ones() -> None:
    snapshot = {**_feed().snapshot(), "milestone_done": {"m-1": 2, "m-2": 5}}

    assert slim_snapshot(snapshot)["milestone_done"] == {"m-1": 5, "m-2": 5}


def test_snapshot_slim_encodes_to_the_bytes_the_slimmed_document_makes() -> None:
    feed = _feed()
    snapshot = feed.snapshot()

    assert encode_snapshot(snapshot, {}) == encode("snapshot", slim_snapshot(snapshot))


def test_snapshot_slim_is_under_a_quarter_of_the_unslimmed_encoding() -> None:
    feed = _feed()
    for n in range(40):
        feed.put(task(f"BULK-{n}", "To Do", description="d" * 2000, moves=OPEN))
    snapshot = feed.snapshot()

    assert len(encode_snapshot(snapshot, {})) < 0.25 * len(encode("snapshot", snapshot))


def test_the_snapshot_and_the_pulls_event_omit_the_fields_of_a_pull_record_the_api_does_not_declare() -> None:
    record = {
        "number": 7,
        "repo": "o/r",
        "url": "https://github.com/o/r/pull/7",
        "checks": "pass",
        "merged": True,
        "merge_sha": "a" * 40,
        "merged_at": "2026-10-07T00:00:00Z",
        "threads": 0,
        "stale": False,
        "files": ["README.md"],
        "applied_by": "b" * 40,
    }
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    _, events = feed.subscribe()
    feed.set_pulls({"TASK-1": [record]})

    kind, delta = events.get_nowait()
    sent = [json.loads(event(kind, delta))["pulls"], _sent(feed)["pulls"]]

    assert kind == "pulls"
    for pulls in sent:
        assert {"files", "applied_by"}.isdisjoint(pulls["TASK-1"][0])
        assert pulls["TASK-1"][0]["number"] == 7


def test_a_snapshot_event_omits_the_fields_of_a_pull_record_the_api_does_not_declare() -> None:
    record = {
        "number": 7,
        "repo": "o/r",
        "url": "https://github.com/o/r/pull/7",
        "checks": "pass",
        "merged": False,
        "merge_sha": None,
        "merged_at": None,
        "threads": 0,
        "behind_main": 0,
        "stale": False,
        "files": ["README.md"],
        "applied_by": "b" * 40,
    }
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.set_pulls({"TASK-1": [record]})

    sent = json.loads(event("snapshot", feed.snapshot()))["pulls"]["TASK-1"][0]

    assert {"files", "applied_by"}.isdisjoint(sent)
    assert sent["number"] == 7
