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
    feed.put(BoardTask(id="PROJ-1", title="t", lane="to_do"))

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
    feed.put(BoardTask(id="PROJ-1", title="t", lane="done", settled="completed"))

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
        "pulls",
        "settled",
    ]
    assert body["graphs"] == [*FLOWS, "runs"]
    assert (body["flows"][0]["name"], body["flows"][0]["machine"]) == ("board", MACHINES["board"])
    assert (body["dags"], body["pulls"], body["claims"], body["settled"], body["error"]) == (
        [],
        {},
        {},
        {"PROJ-1": "completed"},
        None,
    )
    assert body["boardUrl"] == "http://tracker.example.test:6421"
    assert abs(body["now"] - time.time()) < 60


PROJ = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))


def test_a_board_task_an_adapter_wrote_is_an_agent_in_its_lane() -> None:
    feed = BoardFeed(keys=PROJ)
    _, changes = feed.subscribe()

    feed.put(
        BoardTask(
            id="PROJ-1",
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
        }
    ]
    assert changes.get_nowait()[0] == "task"


def test_a_task_that_changed_lane_carries_the_lane_it_left_until_it_changes_again() -> None:
    feed = BoardFeed()
    waiting = BoardTask(id="PROJ-1", title="t", lane="waiting")
    ready = BoardTask(id="PROJ-1", title="t", lane="ready")

    feed.put(waiting)
    assert "previous" not in _agents(feed)[0]  # first seen: it left no lane

    feed.put(ready)
    _, changes = feed.subscribe()
    feed.put(ready)  # the hourly reconcile republishes it unchanged

    assert _agents(feed)[0]["previous"] == "waiting"
    assert changes.empty()

    feed.put(BoardTask(id="PROJ-1", title="t", lane="in_progress"))
    assert _agents(feed)[0]["previous"] == "ready"


def test_a_settled_task_republished_unchanged_is_no_delta_and_a_reopened_one_is_no_longer_settled() -> None:
    feed = BoardFeed()
    done = BoardTask(id="PROJ-1", title="t", lane="done", settled="completed")
    feed.put(done)
    _, changes = feed.subscribe()

    feed.put(done)  # the hourly reconcile republishes it unchanged

    assert changes.empty()
    feed.put(BoardTask(id="PROJ-1", title="t", lane="ready"))
    assert feed.snapshot()["settled"] == {}


def test_a_settled_board_task_leaves_its_lane_and_a_task_outside_the_scheme_is_not_placed() -> None:
    feed = BoardFeed(keys=PROJ)
    feed.put(BoardTask(id="PROJ-1", title="t", lane="done"))

    feed.put(BoardTask(id="PROJ-1", title="t", lane="done", settled="completed"))
    feed.put(BoardTask(id="OPS-9", title="t", lane="to_do"))

    body = feed.snapshot()
    assert (_agents(feed), body["settled"]) == ([], {"PROJ-1": "completed"})
