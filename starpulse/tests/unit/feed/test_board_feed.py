"""The Board the view draws, held in memory from what the board adapter places, and the runs beside it."""

import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from starpulse._internal.config.config import CommitKeys
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse.contracts.adapters import BoardTask, MachineEvent, TaskKeys
from starpulse.contracts.api import event
from starpulse.tests.machines import FLOWS, MACHINES

PR = "https://github.com/acme/widgets/pull/1750"


def _agents(feed: BoardFeed) -> list[dict]:
    return feed.snapshot()["flows"][0]["agents"]


def test_an_unsubscribed_page_gets_no_more_deltas() -> None:
    feed = BoardFeed()
    _, deltas = feed.subscribe()

    feed.unsubscribe(deltas)
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="to_do"))

    assert deltas.empty()


def test_an_instances_runs_arrive_as_a_delta_only_when_they_change() -> None:
    feed = BoardFeed()
    _, deltas = feed.subscribe()

    feed.set_dags("ci", [{"name": "d"}], None)
    feed.set_dags("ci", [{"name": "d"}], None)
    feed.set_dags("ci", [{"name": "d"}], "down")

    assert feed.snapshot()["dags"] == [{"name": "ci/d"}]
    assert feed.snapshot()["error"] == "ci: down"
    first, second = deltas.get_nowait(), deltas.get_nowait()
    assert deltas.empty()
    assert (first[0], first[1]["dags"], first[1]["error"]) == ("dags", [{"name": "ci/d"}], None)
    assert second[1]["error"] == "ci: down"


POOL = {"name": "deliver", "cap": 32, "running": 2, "queued": 1}


def test_pools_are_drawn_under_the_instance_that_reported_them_and_so_is_the_pool_a_dag_names() -> None:
    feed = BoardFeed()
    _, deltas = feed.subscribe()

    feed.set_dags("prod", [{"name": "a", "pool": "deliver"}, {"name": "b", "pool": ""}, {"name": "c"}], None, [POOL])
    feed.set_dags("staging", [{"name": "d", "pool": "deliver"}], None, [{**POOL, "cap": 4}])

    snapshot = feed.snapshot()
    assert snapshot["pools"] == [
        {**POOL, "name": "prod/deliver"},
        {**POOL, "name": "staging/deliver", "cap": 4},
    ]
    assert [d.get("pool") for d in snapshot["dags"]] == ["prod/deliver", "", None, "staging/deliver"]
    kind, delta = deltas.get_nowait()
    assert (kind, delta["pools"]) == ("dags", [{**POOL, "name": "prod/deliver"}])


def test_an_instance_that_reports_no_pools_has_none_drawn() -> None:
    feed = BoardFeed()

    feed.set_dags("ci", [{"name": "d"}], None)

    assert feed.snapshot()["pools"] == []
    assert feed.snapshot()["dags"] == [{"name": "ci/d"}]


def test_pools_stay_until_an_instance_reports_others_and_a_read_error_keeps_them() -> None:
    feed = BoardFeed()
    feed.set_dags("ci", [{"name": "d"}], None, [POOL])

    feed.set_dags("ci", [{"name": "d"}], None)  # nothing said about pools: they stay
    feed.set_dags("ci", None, "refused")
    assert feed.snapshot()["pools"] == [{**POOL, "name": "ci/deliver"}]

    feed.set_dags("ci", [{"name": "d"}], None, [])  # the adapter now reports none
    assert feed.snapshot()["pools"] == []


def test_two_instances_draw_both_sets_each_workflow_prefixed_with_its_instance() -> None:
    feed = BoardFeed()
    feed.set_dags("prod", [{"name": "nightly"}, {"name": "backup"}], None)
    feed.set_dags("staging", [{"name": "etl"}], None)

    assert [d["name"] for d in feed.snapshot()["dags"]] == ["prod/nightly", "prod/backup", "staging/etl"]


def test_the_same_workflow_name_on_two_instances_is_two_distinct_workflows() -> None:
    feed = BoardFeed()
    feed.set_dags("prod", [{"name": "nightly", "status": "failed"}], None)
    feed.set_dags("staging", [{"name": "nightly", "status": "succeeded"}], None)

    assert [(d["name"], d["status"]) for d in feed.snapshot()["dags"]] == [
        ("prod/nightly", "failed"),
        ("staging/nightly", "succeeded"),
    ]


def test_one_instance_failing_keeps_the_other_s_runs_and_names_the_failing_one() -> None:
    feed = BoardFeed()
    feed.set_dags("prod", [{"name": "nightly"}], None)
    feed.set_dags("staging", [{"name": "etl"}], None)

    feed.set_dags("staging", None, "refused")

    body = feed.snapshot()
    assert [d["name"] for d in body["dags"]] == ["prod/nightly", "staging/etl"]
    assert body["error"] == "staging: refused"


def test_a_recovered_instance_clears_its_error_and_two_failures_are_both_named() -> None:
    feed = BoardFeed()
    feed.set_dags("prod", None, "refused")
    feed.set_dags("staging", None, "timed out")
    assert feed.snapshot()["error"] == "prod: refused; staging: timed out"

    feed.set_dags("prod", [], None)

    assert feed.snapshot()["error"] == "staging: timed out"


def test_an_instances_sink_publishes_under_its_own_name() -> None:
    feed = BoardFeed()

    feed.runs("ci").set_dags([{"name": "d"}], None)

    assert [d["name"] for d in feed.snapshot()["dags"]] == ["ci/d"]


def test_the_domains_and_run_safe_the_feed_is_given_are_what_the_snapshot_declares() -> None:
    feed = BoardFeed(
        machines=MACHINES, domains={"Ops": ("prod/nightly", "staging/nightly")}, run_safe=("staging/nightly",)
    )

    assert feed.snapshot()["domains"] == [
        {
            "name": "Ops",
            "dags": [{"name": "prod/nightly", "runSafe": False}, {"name": "staging/nightly", "runSafe": True}],
            "processes": [],
        }
    ]


def test_the_feed_is_not_ready_until_the_stream_is_read_to_the_id_it_was_told_to_expect() -> None:
    feed = BoardFeed()
    feed.expect("5-0")

    feed.seen("4-9")
    assert not feed.ready.is_set()
    feed.seen("5-0")
    assert feed.ready.is_set()


def test_a_feed_told_to_expect_an_empty_stream_is_ready() -> None:
    feed = BoardFeed()

    feed.expect("0-0")

    assert feed.ready.is_set()


def test_a_feed_builds_when_no_finished_task_files_exist(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    feed = BoardFeed()

    feed.expect("0-0")

    body = feed.snapshot()
    assert body["settled"] == {}
    assert body["error"] is None


def test_stream_ids_compare_by_number_not_by_text() -> None:
    feed = BoardFeed()
    feed.expect("10-0")

    feed.seen("9-0")

    assert not feed.ready.is_set()


def test_a_feed_still_connecting_to_the_stream_says_so() -> None:
    feed = BoardFeed(source="q:tasks")

    feed.await_stream()

    assert feed.snapshot()["error"] == "board: reading q:tasks"


def test_a_feed_given_no_source_says_it_is_reading_the_board() -> None:
    feed = BoardFeed()

    feed.await_stream()

    assert feed.snapshot()["error"] == "board: reading the board"


def test_a_snapshot_before_the_stream_is_read_says_so() -> None:
    feed = BoardFeed(source="q:tasks")
    feed.expect("5-0")

    assert feed.snapshot()["error"] == "board: reading q:tasks"

    feed.seen("5-0")
    assert feed.snapshot()["error"] is None


def test_a_page_connected_while_the_stream_is_replayed_gets_one_snapshot_once_it_is_read_not_every_replayed_step() -> (
    None
):
    feed = BoardFeed(keys=PROJ)
    feed.expect("5-0")
    first, changes = feed.subscribe()

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="in_progress"))
    feed.put(BoardTask(id="PROJ-2", team="demo", title="u", lane="review"))
    feed.seen("4-0")
    assert changes.empty()

    feed.seen("5-0")

    kind, body = changes.get_nowait()
    assert changes.empty()
    assert (first["reading"], kind, body["reading"]) == (True, "snapshot", False)
    assert {a["id"]: a["state"] for a in body["flows"][0]["agents"]} == {"PROJ-1": "in_progress", "PROJ-2": "review"}


#: Delta kinds a restart must not resend: the snapshot at the end of replay carries their result.
_REPLAY_DELTAS = (
    "task",
    "move",
    "insight",
    "pulls",
    "claim",
    "dags",
    "ledgers",
    "level",
    "forwarding",
    "autopilot",
)


def test_a_replay_resends_only_the_snapshot_not_delta_kinds() -> None:
    feed = BoardFeed()
    feed.expect("1-0")
    _, changes = feed.subscribe()
    for kind in _REPLAY_DELTAS:
        feed.publish(kind, {"id": kind})

    assert changes.empty()

    feed.seen("1-0")
    assert changes.get_nowait()[0] == "snapshot"
    assert changes.empty()


def test_the_sequence_half_of_a_stream_id_orders_entries_that_share_a_millisecond() -> None:
    feed = BoardFeed()
    feed.expect("5-1")

    feed.seen("5-0")
    assert not feed.ready.is_set()
    feed.seen("5-1")
    assert feed.ready.is_set()


@pytest.mark.parametrize("last_id", ["1-0", "0-1"])
def test_a_feed_that_has_read_nothing_is_not_ready_for_the_first_entry_of_a_stream(last_id: str) -> None:
    feed = BoardFeed()

    feed.expect(last_id)

    assert not feed.ready.is_set()


def test_a_stream_id_with_no_sequence_counts_as_sequence_zero() -> None:
    feed = BoardFeed()
    feed.expect("5-1")

    feed.seen("5")

    assert not feed.ready.is_set()


def test_the_board_snapshot_has_the_shape_the_page_reads() -> None:
    feed = BoardFeed(board_url="http://tracker.example.test:6421", machines=MACHINES)
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="done", settled="completed"))

    body = feed.snapshot()

    assert sorted(body) == [
        "boardUrl",
        "capabilities",
        "claims",
        "cold_done",
        "cues",
        "dags",
        "domains",
        "error",
        "flows",
        "graphs",
        "hint",
        "insights",
        "machinePage",
        "machineStrip",
        "mergePins",
        "mergeStrip",
        "now",
        "pools",
        "pulls",
        "reading",
        "settled",
    ]
    assert body["graphs"] == [*FLOWS, "runs"]
    assert (body["flows"][0]["name"], body["flows"][0]["machine"]) == ("board", MACHINES["board"])
    assert (body["dags"], body["pulls"], body["claims"], body["settled"], body["error"]) == (
        [],
        {},
        {},
        {
            "PROJ-1": {
                "state": "completed",
                "at": None,
                "created": None,
                "title": "t",
                "model": "",
                "milestone": "",
                "labels": [],
            }
        },
        None,
    )
    assert body["boardUrl"] == "http://tracker.example.test:6421"
    assert abs(body["now"] - time.time()) < 60


PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))


def test_an_agent_pairs_each_criterion_with_its_tick_and_leaves_one_past_the_ticks_unchecked() -> None:
    feed = BoardFeed(keys=PROJ, clock=lambda: 7.0)

    feed.put(
        BoardTask(
            id="PROJ-1",
            team="demo",
            title="t",
            lane="needs_attention",
            acceptance_criteria=("a", "b", "c"),
            acceptance_checked=(True, False),
            pause_reason="Pick one",
        )
    )

    [agent] = _agents(feed)
    assert agent["criteria"] == [
        {"text": "a", "checked": True},
        {"text": "b", "checked": False},
        {"text": "c", "checked": False},
    ]
    assert agent["pause_reason"] == "Pick one"


def test_a_board_task_an_adapter_wrote_is_an_agent_in_its_lane() -> None:
    feed = BoardFeed(keys=PROJ, clock=lambda: 7.0)
    _, changes = feed.subscribe()

    feed.put(
        BoardTask(
            id="PROJ-1",
            team="demo",
            title="Add thing",
            lane="in_progress",
            dependencies=("PROJ-0",),
            references=(PR, "docs/x.md"),
            profile="claude-opus",
            labels=("spike",),
            milestone="m-3",
            description="Draw it.",
        )
    )

    assert _agents(feed) == [
        {
            "id": "PROJ-1",
            "title": "Add thing",
            "state": "in_progress",
            "model": "claude-opus",
            "holder": "",
            "labels": ["spike"],
            "milestone": "m-3",
            "type": "",
            "dependencies": ["PROJ-0"],
            "prs": [PR],
            "runs": [],
            "description": "Draw it.",
            "criteria": [],
            "pause_reason": "",
            "moves": {},  # an adapter that writes no verdicts offers no guarded column
            "entered": 7.0,
            "created": None,  # an adapter that does not say when a task was created
            "workable": False,  # PROJ-0 is not on the Board, so it is not done
            "workable_since": None,
        }
    ]
    assert changes.get_nowait()[0] == "task"


def test_a_task_that_changed_lane_carries_the_lane_it_left_until_it_changes_again() -> None:
    feed = BoardFeed()
    waiting = BoardTask(id="PROJ-1", team="demo", title="t", lane="waiting")
    ready = BoardTask(id="PROJ-1", team="demo", title="t", lane="ready")

    feed.put(waiting)
    assert "previous" not in _agents(feed)[0]  # first seen: it left no lane

    feed.put(ready)
    _, changes = feed.subscribe()
    feed.put(ready)  # the hourly reconcile republishes it unchanged

    assert _agents(feed)[0]["previous"] == "waiting"
    assert changes.empty()

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="in_progress"))
    assert _agents(feed)[0]["previous"] == "ready"


def test_a_settled_task_republished_unchanged_is_no_delta_and_a_reopened_one_is_no_longer_settled() -> None:
    feed = BoardFeed()
    done = BoardTask(id="PROJ-1", team="demo", title="t", lane="done", settled="completed")
    feed.put(done)
    _, changes = feed.subscribe()

    feed.put(done)  # the hourly reconcile republishes it unchanged

    assert changes.empty()
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))
    assert feed.snapshot()["settled"] == {}


def test_a_settled_board_task_leaves_its_lane_and_a_task_outside_the_scheme_is_not_placed() -> None:
    feed = BoardFeed(keys=PROJ)
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="done"))

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="done", settled="completed"))
    feed.put(BoardTask(id="OPS-9", team="demo", title="t", lane="to_do"))

    body = feed.snapshot()
    assert (_agents(feed), body["settled"]["PROJ-1"]["state"]) == ([], "completed")


def test_a_task_read_live_is_stamped_when_it_entered_its_lane_and_keeps_that_time_until_it_changes_lane() -> None:
    now = [100.0]
    feed = BoardFeed(clock=lambda: now[0])
    feed.expect("0-0")  # read up to the stream's end: every put from here is live
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))

    now[0] = 200.0
    feed.put(
        BoardTask(id="PROJ-1", team="demo", title="edited", lane="ready")
    )  # an edit in place, or the hourly reconcile
    assert _agents(feed)[0]["entered"] == 100.0

    feed.put(BoardTask(id="PROJ-1", team="demo", title="edited", lane="in_progress"))
    assert _agents(feed)[0]["entered"] == 200.0


def test_a_task_replayed_before_the_feed_is_ready_takes_its_lane_entry_from_the_history() -> None:
    path = {
        "PROJ-1": [
            {"at": 10.0, "from": None, "to": "In Progress"},
            {"at": 20.0, "from": "In Progress", "to": "Review"},
            {"at": 30.0, "from": "Review", "to": "In Progress"},
        ]
    }
    feed = BoardFeed(clock=lambda: 500.0)
    feed.date_lanes(lambda task: path.get(task, []))
    feed.expect("5-0")

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="in_progress"))
    feed.put(BoardTask(id="PROJ-2", team="demo", title="t", lane="ready"))  # the history never saw it

    assert [a["entered"] for a in _agents(feed)] == [30.0, 500.0]


def test_a_history_that_cannot_be_read_dates_a_replayed_lane_by_the_clock_and_still_places_the_task() -> None:
    def down(_task: str) -> list[dict]:
        raise OSError("history down")

    feed = BoardFeed(clock=lambda: 500.0)
    feed.date_lanes(down)
    feed.expect("5-0")

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))

    assert [(a["id"], a["entered"]) for a in _agents(feed)] == [("PROJ-1", 500.0)]


def test_a_task_carries_when_it_was_created_and_a_settled_one_when_as_whom_and_in_which_milestone_it_settled() -> None:
    # A settled task keeps its labels too: an analytic that asks what a finished task was for reads them here.
    feed = BoardFeed()
    feed.put(BoardTask(id="PROJ-1", team="demo", title="open one", lane="ready", created_at=100.0))
    _, changes = feed.subscribe()

    feed.put(
        BoardTask(
            id="PROJ-2",
            team="demo",
            title="done one",
            lane="done",
            profile="opus",
            milestone="m-7",
            labels=["validation"],
            settled="archived",
            created_at=50.0,
            settled_at=200.0,
        )
    )

    entry = {
        "state": "archived",
        "at": 200.0,
        "created": 50.0,
        "title": "done one",
        "model": "opus",
        "milestone": "m-7",
        "labels": ["validation"],
    }
    assert _agents(feed)[0]["created"] == 100.0
    assert feed.snapshot()["settled"] == {"PROJ-2": entry}
    assert changes.get_nowait() == ("task", {"id": "PROJ-2", "agent": None, "settled": entry})


def test_a_retracted_task_leaves_the_board_and_publishes_once() -> None:
    feed = BoardFeed()
    feed.put(BoardTask(id="task-1", team="demo", title="T", lane="to_do"))
    _, events = feed.subscribe()

    feed.retract("task-1")
    feed.retract("task-1")

    assert feed.task("task-1") is None
    assert events.qsize() == 1


def _run_flags(feed: BoardFeed) -> dict[str, bool]:
    return {d["name"]: d["runSafe"] for d in feed.snapshot()["domains"][0]["dags"]}


def _kinds(deltas) -> list[str]:
    kinds = []
    while not deltas.empty():
        kinds.append(deltas.get_nowait()[0])
    return kinds


def test_run_now_is_declared_only_on_the_run_safe_workflows_its_adapter_reports_startable() -> None:
    names = ("gh/ci.yml", "gh/ui.yml", "dagu/nightly")
    feed = BoardFeed(domains={"Ops": names}, run_safe=names)
    _, deltas = feed.subscribe()

    feed.runs("gh").set_dags([], None, startable=["ui.yml"])
    assert _run_flags(feed) == {"gh/ci.yml": False, "gh/ui.yml": True, "dagu/nightly": True}
    assert _kinds(deltas) == ["dags", "snapshot"]

    feed.runs("gh").set_dags([], None)  # None keeps the last the adapter reported
    assert (_run_flags(feed), _kinds(deltas)) == ({"gh/ci.yml": False, "gh/ui.yml": True, "dagu/nightly": True}, [])

    feed.runs("gh").set_dags([], None, startable=["ci.yml", "ui.yml"])
    assert _run_flags(feed) == {"gh/ci.yml": True, "gh/ui.yml": True, "dagu/nightly": True}
    assert _kinds(deltas) == ["snapshot"]


def test_a_workflow_the_adapter_reports_startable_but_config_does_not_declare_run_safe_stays_off() -> None:
    feed = BoardFeed(domains={"Ops": ("gh/ci.yml", "gh/ui.yml")}, run_safe=("gh/ui.yml",))

    feed.runs("gh").set_dags([], None, startable=["ci.yml", "ui.yml"])

    assert _run_flags(feed) == {"gh/ci.yml": False, "gh/ui.yml": True}


SHA = "a" * 40
LEDGER_MACHINE = {
    "states": [
        {"id": "to_do", "name": "To Do", "initial": True, "final": False},
        {"id": "in_progress", "name": "In Progress", "initial": False, "final": False},
        {"id": "done", "name": "Done", "initial": False, "final": True},
    ],
    "transitions": [
        {"source": "to_do", "target": "in_progress", "event": "STARTED"},
        {"source": "in_progress", "target": "done", "event": "MERGED"},
    ],
    "writers": {"STARTED": [{"actor": "ci/start", "trigger": "task started"}]},
}
CUE = {"event": "MERGED", "dag": "ci/apply", "on": "merge", "resolves": "forced", "state": "done"}
MERGED_PR = {
    "url": "https://github.com/o/trantor/pull/7",
    "merged": True,
    "merge_sha": SHA,
    "merged_at": "2026-10-07T00:01:00Z",
}
APPLIED = {
    "runId": "r1",
    "status": "succeeded",
    "startedAt": "2026-10-07T00:02:00Z",
    "finishedAt": "2026-10-07T00:03:00Z",
    "params": {"AFTER": SHA},
    "steps": {"validate": "succeeded", "deploy": "succeeded"},
}


def _dag(name: str, *recent: dict) -> dict:
    return {
        "name": name,
        "status": "not_started",
        "runId": "",
        "startedAt": "",
        "finishedAt": "",
        "steps": [],
        "recent": list(recent),
    }


def ledger_feed() -> BoardFeed:
    return BoardFeed(
        clock=lambda: datetime(2026, 10, 7, 1, tzinfo=ZoneInfo("UTC")).timestamp(),
        machines={"board": LEDGER_MACHINE},
        domains={"ci": ["ci/apply", "ci/start"]},
        cues=[CUE],
        commit={"ci": CommitKeys(after="AFTER", force="FORCE", task="TASK")},
    )


def test_the_snapshot_carries_each_merge_with_its_tasks_pr_cued_run_and_per_step_status() -> None:
    feed = ledger_feed()
    feed.set_pulls({"TASK-1": [MERGED_PR]})

    feed.set_dags("ci", [_dag("apply", APPLIED)], None)

    (row,) = _head(feed, "MERGED")
    assert (row["sha"], row["tasks"]) == (SHA, ["TASK-1"])
    assert row["pr"] == {"repo": "trantor", "number": 7, "url": MERGED_PR["url"]}
    run = row["runs"]["ci/apply"]
    assert (run["runId"], run["status"], run["inferred"], run["ambiguous"]) == ("r1", "succeeded", False, 0)
    assert run["steps"] == {"validate": "succeeded", "deploy": "succeeded"}


def test_a_merge_no_run_has_reached_is_a_row_with_no_runs() -> None:
    feed = ledger_feed()
    feed.set_pulls({"TASK-1": [MERGED_PR]})
    feed.set_dags("ci", [_dag("apply")], None)

    assert _head(feed, "MERGED")[0]["runs"] == {}


def test_the_workflow_listing_the_page_draws_leaves_the_recent_runs_to_the_ledgers() -> None:
    feed = ledger_feed()
    feed.set_dags("ci", [_dag("apply", APPLIED)], None)

    (dag,) = feed.snapshot()["dags"]
    assert dag["name"] == "ci/apply"
    assert "recent" not in dag


def test_a_feed_that_ties_no_workflow_to_an_event_has_no_ledgers() -> None:
    feed = BoardFeed()
    feed.set_pulls({"TASK-1": [MERGED_PR]})

    assert feed.ledger_rows("MERGED", None, 20) is None
    assert feed.tied("ci") == frozenset()


def test_the_workflows_tied_to_an_instance_are_those_a_cue_or_a_writer_names() -> None:
    feed = ledger_feed()

    assert feed.tied("ci") == {"apply", "start"}
    assert feed.tied("other") == frozenset()
    assert feed.runs("ci").tied == {"apply", "start"}


def test_a_ledgers_event_is_sent_when_a_pull_changes_the_strip_and_not_when_only_a_row_changes() -> None:
    feed = ledger_feed()
    _, deltas = feed.subscribe()

    feed.set_pulls({"TASK-1": [MERGED_PR]})
    feed.set_dags("ci", [_dag("apply", APPLIED)], None)  # pairs the row with its run: the strip and pins stand
    feed.set_dags("ci", [_dag("apply", APPLIED)], "down")  # the same ledgers, a new error

    kinds = []
    while not deltas.empty():
        kinds.append(deltas.get_nowait()[0])
    assert kinds == ["pulls", "ledgers", "dags", "dags"]


def test_the_ledger_is_rebuilt_only_when_a_run_of_a_tied_workflow_changes() -> None:
    feed = ledger_feed()
    feed.set_pulls({"TASK-1": [MERGED_PR]})
    built: list[int] = []
    build_ledger = feed._ledger
    feed._ledger = lambda *args: built.append(1) or build_ledger(*args)  # type: ignore[method-assign]

    feed.set_dags("ci", [_dag("apply", APPLIED)], None)
    feed.set_dags("ci", [_dag("apply", APPLIED), _dag("untied", APPLIED)], None)  # a workflow no event ties
    feed.set_dags("ci", [_dag("apply", APPLIED), _dag("untied", APPLIED)], "down")  # a new error
    feed.set_dags("ci", [_dag("apply", APPLIED), _dag("untied", {**APPLIED, "runId": "r9"})], "down")
    assert len(built) == 1

    feed.set_dags("ci", [_dag("apply", {**APPLIED, "status": "failed"}), _dag("untied")], "down")
    assert len(built) == 2


def test_a_task_entering_the_lane_a_workflows_event_reaches_pairs_with_its_run_by_the_task_parameter() -> None:
    feed = ledger_feed()
    entered = datetime(2026, 10, 7, 0, 5, tzinfo=ZoneInfo("UTC")).timestamp()
    feed.read_lanes(lambda since=None: [("TASK-1", entered, "To Do", "In Progress"), ("TASK-2", entered + 1, "To Do", "In Progress")])
    started = {**APPLIED, "runId": "s1", "startedAt": "2026-10-07T00:06:00Z", "params": {"TASK": "TASK-1"}}

    feed.set_dags("ci", [_dag("start", started)], None)

    rows = _head(feed, "STARTED")
    assert [r["tasks"] for r in rows] == [["TASK-2"], ["TASK-1"]]
    assert "sha" not in rows[0]
    assert rows[1]["runs"]["ci/start"]["runId"] == "s1"
    assert rows[1]["runs"]["ci/start"]["inferred"] is False
    assert rows[0]["runs"] == {}


def test_the_ledger_reads_only_the_lane_changes_of_its_window_from_the_history() -> None:
    feed = ledger_feed()
    asked: list[float | None] = []

    def lane_rows(since: float | None = None) -> list:
        asked.append(since)
        return []

    feed.read_lanes(lane_rows)
    feed.set_dags("ci", [_dag("apply", APPLIED)], None)

    assert asked == [datetime(2026, 10, 6, 1, tzinfo=ZoneInfo("UTC")).timestamp()]


def test_a_page_request_reads_the_ledger_last_built_and_queries_no_lane_history() -> None:
    feed = ledger_feed()
    asked: list[float | None] = []

    def lane_rows(since: float | None = None) -> list:
        asked.append(since)
        return []

    feed.read_lanes(lane_rows)
    feed.set_pulls({"TASK-1": [MERGED_PR]})
    feed.set_dags("ci", [_dag("apply", FAILED)], None)
    built = len(asked)

    assert _head(feed, "MERGED")[0]["sha"] == SHA
    assert feed.ledger_rows("MERGED", None, 5)["rows"][0]["sha"] == SHA
    assert feed.open_failure("ci/apply") == {"runId": "r-bad", "params": FAILED["params"]}
    assert len(asked) == built


def test_the_ledger_is_built_while_page_requests_still_take_the_board() -> None:
    feed = ledger_feed()
    feed.put(BoardTask(id="TASK-9", team="demo", title="t", lane="to_do"))
    building, release = threading.Event(), threading.Event()

    def lane_rows(since: float | None = None) -> list:
        if since is not None:  # the Ledger's window
            building.set()
            release.wait(5)
        return []

    feed.read_lanes(lane_rows)
    feed.snapshot()
    worker = threading.Thread(target=feed.set_dags, args=("ci", [_dag("apply", APPLIED)], None))
    worker.start()
    assert building.wait(5)

    answered = []
    reader = threading.Thread(target=lambda: answered.extend([feed.task("TASK-9"), feed.snapshot()]))
    reader.start()
    reader.join(2)
    answered_while_building = list(answered)
    release.set()
    worker.join(5)

    assert answered_while_building and answered_while_building[0]["id"] == "TASK-9"


def test_a_task_lookup_does_not_wait_for_the_board_lock() -> None:
    feed = BoardFeed()
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="to_do"))
    answered = []

    with feed._lock:
        reader = threading.Thread(target=lambda: answered.append(feed.task("PROJ-1")))
        reader.start()
        reader.join(2)

    assert answered and answered[0]["id"] == "PROJ-1"


def _recorded_lanes(feed: BoardFeed) -> list[tuple]:
    rows: list[tuple] = []

    class Lanes:
        def record_lane(self, event_id: str, task: str, status: str, at: float) -> bool:
            rows.append((task, at, "To Do", status))
            return True

    feed.record_lanes(Lanes())
    feed.read_lanes(lambda since=None: list(rows))
    return rows


def test_a_live_move_into_a_tied_lane_refreshes_the_ledger() -> None:
    feed = ledger_feed()
    _recorded_lanes(feed)
    feed.set_dags("ci", [_dag("start")], None)
    _, _, changes = feed.watch_ledger("STARTED")

    feed.put(BoardTask(id="TASK-1", team="demo", title="t", lane="in_progress"))

    assert [r["tasks"] for r in changes.get_nowait()["rows"]] == [["TASK-1"]]
    assert [r["tasks"] for r in _head(feed, "STARTED")] == [["TASK-1"]]


def test_the_replay_builds_the_ledger_once_when_it_reaches_the_entry_it_expected() -> None:
    feed = ledger_feed()
    rows = _recorded_lanes(feed)
    feed.set_dags("ci", [_dag("start")], None)
    feed.expect("2-0")
    _, deltas = feed.subscribe()

    feed.put(BoardTask(id="TASK-1", team="demo", title="t", lane="in_progress"))
    feed.seen("1-0")
    feed.put(BoardTask(id="TASK-2", team="demo", title="t", lane="in_progress"))
    assert len(rows) == 2
    assert _head(feed, "STARTED") == []
    feed.seen("2-0")

    kinds = [deltas.get_nowait()[0] for _ in range(deltas.qsize())]
    assert kinds == ["snapshot"]
    assert sorted(r["tasks"][0] for r in _head(feed, "STARTED")) == ["TASK-1", "TASK-2"]


REOPEN_MACHINE = {
    "states": [
        {"id": "ready", "name": "Ready", "initial": True, "final": False},
        {"id": "in_progress", "name": "In Progress", "initial": False, "final": False},
        {"id": "needs_attention", "name": "Needs attention", "initial": False, "final": False},
        {"id": "done", "name": "Done", "initial": False, "final": True},
    ],
    "transitions": [
        {"source": "ready", "target": "in_progress", "event": "CLAIM"},
        {"source": "in_progress", "target": "needs_attention", "event": "PARK"},
        {"source": "needs_attention", "target": "in_progress", "event": "RESUME"},
        {"source": "in_progress", "target": "done", "event": "FINALIZE"},
        {"source": "done", "target": "ready", "event": "REOPEN"},
        {"source": "done", "target": "in_progress", "event": "REOPEN"},
    ],
    "writers": {"REOPEN": [{"actor": "ci/start", "trigger": "reopen a done task"}]},
}


def _reopen_rows(*moves: tuple[str, str]) -> list:
    feed = BoardFeed(
        clock=lambda: datetime(2026, 10, 7, 1, tzinfo=ZoneInfo("UTC")).timestamp(),
        machines={"board": REOPEN_MACHINE},
        domains={"ci": ["ci/start"]},
    )
    at = datetime(2026, 10, 7, 0, 30, tzinfo=ZoneInfo("UTC")).timestamp()
    rows = [("TASK-1", at + i, old, new) for i, (old, new) in enumerate(moves)]
    feed.read_lanes(lambda since=None: rows)
    feed.set_dags("ci", [_dag("start")], None)
    page = feed.ledger_rows("REOPEN", None, 20)
    return [r["tasks"] for r in page["rows"]] if page else []


def test_reopen_ledger_adds_no_row_for_a_flap_that_ends_done() -> None:
    flap = [("In Progress", "Needs attention"), ("Needs attention", "In Progress"), ("In Progress", "Done")]

    assert _reopen_rows(*flap) == []


def test_reopen_ledger_adds_one_row_for_a_move_out_of_done() -> None:
    assert _reopen_rows(("In Progress", "Done"), ("Done", "Ready")) == [["TASK-1"]]

BEFORE = "0" * 40
FAILED = {
    **APPLIED,
    "runId": "r-bad",
    "status": "failed",
    "params": {"AFTER": SHA, "BEFORE": BEFORE},
    "steps": {"validate": "succeeded", "deploy": "failed"},
}
FORCED_GREEN = {
    **APPLIED,
    "runId": "r-forced",
    "startedAt": "2026-10-07T00:10:00Z",
    "finishedAt": "2026-10-07T00:11:00Z",
    "params": {"AFTER": SHA, "BEFORE": BEFORE, "FORCE": "1"},
}


def cued_feed(resolves: str) -> BoardFeed:
    feed = BoardFeed(
        clock=lambda: datetime(2026, 10, 7, 1, tzinfo=ZoneInfo("UTC")).timestamp(),
        machines={"board": LEDGER_MACHINE},
        domains={"ci": ["ci/apply", "ci/start"]},
        cues=[{**CUE, "resolves": resolves}],
        commit={"ci": CommitKeys(after="AFTER", before="BEFORE", force="FORCE")},
    )
    feed.set_pulls({"TASK-1": [MERGED_PR]})
    return feed


def test_a_failed_cued_run_pins_its_merge_with_the_rule_its_cue_declares() -> None:
    feed = cued_feed("forced")

    feed.set_dags("ci", [_dag("apply", FAILED)], None)

    (row,) = _head(feed, "MERGED")
    assert row["pinned"] is True
    fail = row["fails"]["ci/apply"]
    assert (fail["runId"], fail["step"], fail["resolves"], fail["resolved"]) == ("r-bad", "deploy", "forced", None)


def test_a_pinned_merge_unpins_on_the_run_its_cue_accepts_and_the_ledgers_event_says_so() -> None:
    feed = cued_feed("forced")
    feed.set_dags("ci", [_dag("apply", FAILED)], None)
    _, _, changes = feed.watch_ledger("MERGED")

    feed.set_dags("ci", [_dag("apply", FAILED, FORCED_GREEN)], None)

    assert changes.get_nowait()["rows"][0]["pinned"] is False


def test_a_failure_whose_cue_resolves_next_clears_on_any_later_green_run_but_a_forced_one_does_not() -> None:
    later = {**APPLIED, "runId": "r-next", "startedAt": "2026-10-07T00:10:00Z", "params": {}}
    nxt, forced = cued_feed("next"), cued_feed("forced")

    for feed in (nxt, forced):
        feed.set_dags("ci", [_dag("apply", FAILED, later)], None)

    assert _head(nxt, "MERGED")[0]["pinned"] is False
    assert _head(forced, "MERGED")[0]["pinned"] is True


def test_the_open_failure_of_a_workflow_is_its_failed_run_with_the_parameters_it_started_with() -> None:
    feed = cued_feed("forced")
    feed.set_dags("ci", [_dag("apply", FAILED)], None)

    assert feed.open_failure("ci/apply") == {"runId": "r-bad", "params": {"AFTER": SHA, "BEFORE": BEFORE}}


def test_a_workflow_with_no_open_failure_has_none() -> None:
    feed = cued_feed("forced")
    feed.set_dags("ci", [_dag("apply", FAILED, FORCED_GREEN)], None)

    assert feed.open_failure("ci/apply") is None
    assert feed.open_failure("ci/start") is None
    assert feed.open_failure("unknown/apply") is None


def test_the_open_failure_is_the_newest_when_several_merges_are_pinned() -> None:
    older = {**FAILED, "runId": "r-old", "startedAt": "2026-10-07T00:02:00Z", "params": {"AFTER": "b" * 40}}
    feed = cued_feed("forced")
    feed.set_pulls(
        {
            "TASK-1": [MERGED_PR],
            "TASK-0": [{**MERGED_PR, "url": "https://github.com/o/trantor/pull/6", "merge_sha": "b" * 40, "merged_at": "2026-10-06T23:00:00Z"}],
        }
    )

    feed.set_dags("ci", [_dag("apply", older, {**FAILED, "startedAt": "2026-10-07T00:20:00Z"})], None)

    assert feed.open_failure("ci/apply")["runId"] == "r-bad"


def test_the_commit_keys_of_an_instance_are_those_its_config_declares() -> None:
    feed = cued_feed("forced")

    assert feed.commit_keys("ci") == CommitKeys(after="AFTER", before="BEFORE", force="FORCE")
    assert feed.commit_keys("other") is None


def test_the_snapshot_links_a_pinned_repositorys_merge_to_the_bump_merge_that_applies_it() -> None:
    skills = {**MERGED_PR, "url": "https://github.com/o/skills/pull/2", "merge_sha": "b" * 40, "applied_by": SHA}
    feed = ledger_feed()
    feed.set_pulls({"TASK-1": [MERGED_PR], "TASK-2": [skills]})
    feed.set_dags("ci", [_dag("apply", APPLIED)], None)

    rows = {row["sha"]: row for row in _head(feed, "MERGED")}

    assert rows["b" * 40]["appliedBy"] == SHA
    assert rows["b" * 40]["runs"] == {}
    assert rows[SHA]["applies"] == ["b" * 40]
    assert rows[SHA]["runs"]["ci/apply"]["runId"] == "r1"


def _merged(n: int, minute: int, day: int = 7) -> tuple[str, list[dict]]:
    """Task `TASK-<n>`'s pull request, merged at `minute` past midnight UTC on October `day` as commit `<n>` repeated."""
    at = f"2026-10-{day:02d}T{minute // 60:02d}:{minute % 60:02d}:00Z"
    return f"TASK-{n}", [
        {
            "number": n,
            "url": f"https://github.com/o/trantor/pull/{n}",
            "checks": "pass",
            "merged": True,
            "merge_sha": f"{n:040x}",
            "merged_at": at,
            "threads": 0,
            "stale": False,
        }
    ]


def _paged_feed() -> BoardFeed:
    """25 merges in the last 24 hours, minutes 0-24 of October 7th; one on October 5th, beyond the edge."""
    feed = ledger_feed()
    feed.set_pulls(dict([_merged(n, n) for n in range(25)] + [_merged(99, 0, day=5)]))
    run = lambda rid, sha, start, **extra: {  # noqa: E731
        **APPLIED, "runId": rid, "startedAt": f"2026-10-07T00:{start}:00Z", "params": {"AFTER": f"{sha:040x}", **extra},
    }
    failed = {**run("bad", 5, 30), "status": "failed"}
    feed.set_dags("ci", [_dag("apply", failed, run("again", 3, 40, FORCE="true"))], None)
    return feed


def test_the_snapshot_carries_only_the_newest_page_of_merges_and_the_feed_serves_older_ones_to_the_edge() -> None:
    feed = _paged_feed()

    head = _head(feed, "MERGED")
    older = feed.ledger_rows("MERGED", head[-1]["at"], 20)

    assert [row["tasks"] for row in head[:2]] == [["TASK-24"], ["TASK-23"]]
    assert len(head) == 20
    assert [row["tasks"] for row in older["rows"]] == [[f"TASK-{n}"] for n in range(4, -1, -1)]
    assert older["more"] is False


def test_the_snapshot_strip_counts_the_whole_day_of_merges_not_just_the_loaded_page() -> None:
    strip = _paged_feed().snapshot()["mergeStrip"]

    totals = {field: sum(b[field] for b in strip["buckets"]) for field in ("merges", "failed", "reruns")}
    assert totals == {"merges": 25, "failed": 1, "reruns": 1}
    assert strip["bucket"] == 900
    assert len(strip["buckets"]) == 96


def test_a_ledger_watcher_is_sent_the_one_row_a_run_changed_and_not_the_rows_it_left_alone() -> None:
    feed = ledger_feed()
    feed.set_pulls(dict(_merged(n, n) for n in range(5)))
    _, _, changes = feed.watch_ledger("MERGED")

    feed.set_dags("ci", [_dag("apply", {**APPLIED, "params": {"AFTER": f"{2:040x}"}})], None)

    assert [row["tasks"] for row in changes.get_nowait()["rows"]] == [["TASK-2"]]


def test_a_ledger_watcher_is_sent_the_new_row_and_nothing_for_the_row_that_left() -> None:
    feed = ledger_feed()
    feed.set_pulls(dict(_merged(n, n) for n in range(5)))
    _, _, changes = feed.watch_ledger("MERGED")

    feed.set_pulls(dict(_merged(n, n) for n in range(1, 6)))

    assert [row["tasks"] for row in changes.get_nowait()["rows"]] == [["TASK-5"]]


def test_a_pinned_merge_older_than_the_loaded_page_still_rides_the_snapshot_and_the_ledgers_event() -> None:
    feed = ledger_feed()
    feed.set_pulls(dict(_merged(n, n) for n in range(25)))
    failed = {
        **APPLIED, "runId": "bad", "status": "failed", "startedAt": "2026-10-07T00:30:00Z", "params": {"AFTER": f"{2:040x}"},
    }
    _, deltas = feed.subscribe()
    feed.set_dags("ci", [_dag("apply", failed)], None)
    sent = dict(deltas.get_nowait() for _ in range(deltas.qsize()))

    snapshot = feed.snapshot()

    assert [row["tasks"] for row in snapshot["mergePins"]] == [["TASK-2"]]
    assert all(row["tasks"] != ["TASK-2"] for row in _head(feed, "MERGED"))
    assert [row["tasks"] for row in sent["ledgers"]["mergePins"]] == [["TASK-2"]]


def test_a_lane_change_is_recorded_once_and_a_replay_of_its_event_id_adds_no_row(tmp_path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.db'}", {})
    times = iter([100.0, 200.0, 300.0])
    feed = BoardFeed(clock=lambda: next(times))
    feed.record_lanes(store)

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))  # an hourly reconcile is no change
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="in_progress"))
    replay = BoardFeed(clock=iter([100.0, 200.0]).__next__)  # a restart replays the same changes with the same dates
    replay.record_lanes(store)
    replay.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))
    replay.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="in_progress"))

    assert store.lane_path("PROJ-1") == [
        {"at": 100.0, "from": None, "to": "ready"},
        {"at": 200.0, "from": "ready", "to": "in_progress"},
    ]
    with store.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM starpulse_lane_changes")).scalar() == 2


def test_a_history_that_cannot_record_a_lane_change_still_places_the_task() -> None:
    class Down:
        def record_lane(self, *_args: object) -> None:
            raise OSError("history down")

    feed = BoardFeed(clock=lambda: 5.0)
    feed.record_lanes(Down())

    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="ready"))

    assert [a["id"] for a in _agents(feed)] == ["PROJ-1"]


def test_the_snapshot_and_the_pulls_event_carry_only_the_fields_the_api_contract_declares_for_a_pull() -> None:
    record = {
        **MERGED_PR,
        "number": 7,
        "checks": "pass",
        "threads": 0,
        "stale": False,
        "files": ["README.md"],
        "applied_by": SHA,
    }
    feed = ledger_feed()
    _, events = feed.subscribe()
    feed.set_pulls({"TASK-1": [record]})

    kind, delta = events.get_nowait()
    assert kind == "pulls"
    event("pulls", delta)
    event("snapshot", feed.snapshot())
    assert _head(feed, "MERGED")[0]["sha"] == SHA


def test_the_open_tasks_and_a_machines_tasks_can_be_read_without_a_snapshot() -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(BoardTask(id="PROJ-1", team="demo", title="t", lane="review", labels=["size-3"]))
    feed.put(BoardTask(id="PROJ-2", team="demo", title="t", lane="to_do"))
    MachineTasks(feed).put(MachineEvent(machine="in-progress", event="WORKTREE_READY", task="PROJ-1", time=time.time()))

    assert {(t["id"], t["state"], tuple(t["labels"])) for t in feed.open_tasks()} == {
        ("PROJ-1", "review", ("size-3",)),
        ("PROJ-2", "to_do", ()),
    }
    assert [t["state"] for t in feed.machine_tasks("in-progress")] == ["worktree_ready"]
    assert feed.machine_tasks("authoring-skills") == []  # drawn, nothing placed
    assert feed.machine_tasks("not-a-machine") == []


def test_every_task_open_or_settled_is_named_by_its_title_and_labels() -> None:
    feed = BoardFeed()
    feed.put(BoardTask(id="PROJ-1", team="demo", title="open one", lane="ready", labels=["a"]))
    feed.put(
        BoardTask(id="PROJ-2", team="demo", title="done one", lane="done", labels=["validation"], settled="completed")
    )

    assert feed.titled() == {
        "PROJ-1": {"title": "open one", "labels": ["a"]},
        "PROJ-2": {"title": "done one", "labels": ["validation"]},
    }


def test_ledger_deferred_the_snapshot_carries_the_strip_and_pins_but_no_ledger_rows() -> None:
    feed = _paged_feed()

    snapshot = feed.snapshot()

    assert "ledgers" not in snapshot
    assert snapshot["mergeStrip"] is not None
    assert snapshot["mergePins"] is not None


def test_ledger_deferred_a_watcher_is_handed_its_events_head_and_whether_older_rows_remain() -> None:
    feed = _paged_feed()

    rows, more, deltas = feed.watch_ledger("MERGED")

    assert len(rows) == 20
    assert more is True
    assert deltas.empty()
    assert feed.watch_ledger("NOT-AN-EVENT") is None


def test_ledger_deferred_a_row_change_reaches_the_watcher_of_its_event_and_no_other() -> None:
    feed = ledger_feed()
    _recorded_lanes(feed)
    feed.set_dags("ci", [_dag("start")], None)
    merged_rows, _, merged = feed.watch_ledger("MERGED")
    started_rows, _, started = feed.watch_ledger("STARTED")
    _, main = feed.subscribe()
    assert merged_rows == started_rows == []

    feed.put(BoardTask(id="TASK-1", team="demo", title="t", lane="in_progress"))

    delta = started.get_nowait()
    assert [row["tasks"] for row in delta["rows"]] == [["TASK-1"]]
    assert merged.empty()
    assert "ledgers" not in dict(main.get_nowait() for _ in range(main.qsize()))  # nothing for the main stream's rows


def test_ledger_deferred_a_ledgers_delta_on_the_main_stream_holds_no_rows() -> None:
    feed = ledger_feed()
    _, main = feed.subscribe()

    feed.set_pulls(dict(_merged(n, n) for n in range(3)))

    delta = _ledgers_delta(main)
    assert set(delta) == {"mergeStrip", "mergePins"}


def test_ledger_deferred_a_released_watcher_is_sent_nothing() -> None:
    feed = ledger_feed()
    _, _, deltas = feed.watch_ledger("MERGED")
    feed.unwatch_ledger(deltas)

    feed.set_pulls(dict(_merged(n, n) for n in range(3)))

    assert deltas.empty()


def _ledgers_delta(deltas) -> dict:
    return dict(deltas.get_nowait() for _ in range(deltas.qsize()))["ledgers"]


def _head(feed: BoardFeed, event: str) -> list[dict]:
    """The newest page of `event`'s Ledger, as a page opening it is handed it."""
    return (feed.ledger_rows(event, None, 20) or {"rows": []})["rows"]


def test_a_task_card_carries_the_dagu_runs_its_dag_run_ids_name() -> None:
    run = {"runId": "dag-run-task-7-1", "task": "TASK-7", "url": "http://dagu/dag-runs/w/dag-run-task-7-1", "status": "failed", "startedAt": "t"}
    other = {"runId": "r1", "task": None, "url": "http://dagu/dag-runs/w/r1", "status": "succeeded", "startedAt": "t"}
    feed = BoardFeed()
    feed.put(BoardTask(id="TASK-7", team="demo", title="t", lane="in_progress"))
    _, deltas = feed.subscribe()

    feed.set_dags("ci", [{"name": "w", "recent": [run, other]}], None)

    assert _agents(feed)[0]["runs"] == [{"url": run["url"], "status": "failed", "startedAt": "t"}]
    assert [kind for kind, _ in (deltas.get_nowait(), deltas.get_nowait())] == ["dags", "task"]
    feed.put(BoardTask(id="TASK-7", team="demo", title="t", lane="review"))  # a reread keeps them
    assert len(_agents(feed)[0]["runs"]) == 1
