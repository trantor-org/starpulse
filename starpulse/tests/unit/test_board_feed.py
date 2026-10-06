"""The Board the view draws, held in memory from what the board adapter places, and the runs beside it."""

import re
import time

import pytest

from starpulse.board_feed import BoardFeed
from starpulse.contracts import BoardTask, TaskKeys
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
        "cues",
        "dags",
        "domains",
        "error",
        "flows",
        "graphs",
        "hint",
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
        {"PROJ-1": {"state": "completed", "at": None, "created": None, "title": "t", "model": ""}},
        None,
    )
    assert body["boardUrl"] == "http://tracker.example.test:6421"
    assert abs(body["now"] - time.time()) < 60


PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))


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
            assignee="claude-opus",
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
            "labels": ["spike"],
            "milestone": "m-3",
            "dependencies": ["PROJ-0"],
            "prs": [PR],
            "description": "Draw it.",
            "moves": {},  # an adapter that writes no verdicts offers no guarded column
            "entered": 7.0,
            "created": None,  # an adapter that does not say when a task was created
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


def test_a_task_carries_when_it_was_created_and_a_settled_one_when_and_as_whom_it_settled() -> None:
    feed = BoardFeed()
    feed.put(BoardTask(id="PROJ-1", team="demo", title="open one", lane="ready", created_at=100.0))
    _, changes = feed.subscribe()

    feed.put(
        BoardTask(
            id="PROJ-2",
            team="demo",
            title="done one",
            lane="done",
            assignee="opus",
            settled="archived",
            created_at=50.0,
            settled_at=200.0,
        )
    )

    entry = {"state": "archived", "at": 200.0, "created": 50.0, "title": "done one", "model": "opus"}
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
