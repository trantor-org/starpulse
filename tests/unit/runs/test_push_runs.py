"""`PushRuns`: workflows known only from CloudEvent run entries, and the step graph their steps teach."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from starpulse.board.board_feed import BoardFeed, follow
from starpulse.contracts.adapters import Dag
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.history import HistoryStore
from starpulse.runs import run_events
from starpulse.runs.push_runs import PUSHED_INSTANCE, PushedRunsSnapshot, PushRuns

START = 1_700_000_000.0


def fields(
    phase: str, status: str, *, run: str = "r1", at: float = START, workflow: str = "nightly", **step: Any
) -> dict:
    """An entry as the event log holds it: the JSON the ingest appended, a list still a list."""
    return run_events.entry(phase, workflow, run, status, now=at, **step)


def drawn(feed: BoardFeed, name: str = "nightly") -> dict:
    return next(dag for dag in feed.snapshot()["dags"] if dag["name"] == f"{PUSHED_INSTANCE}/{name}")


def edges(dag: dict) -> dict[str, list[str]]:
    return {step["name"]: step["depends"] for step in dag["steps"]}


def test_a_run_start_and_end_move_the_workflow_through_their_statuses() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))

    runs.handle_entry("1-0", fields("StepStarted", "running"))
    assert drawn(feed)["status"] == "running"
    assert drawn(feed)["runId"] == "r1"
    assert drawn(feed)["finishedAt"] == ""

    runs.handle_entry("2-0", fields("StepFinished", "failed", at=START + 60))
    assert drawn(feed)["status"] == "failed"
    assert drawn(feed)["finishedAt"] == "2023-11-14T22:14:20Z"
    Dag.model_validate(drawn(feed))


def test_steps_with_depends_draw_those_edges() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))

    runs.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch"))
    runs.handle_entry("3-0", fields("StepFinished", "succeeded", step="clean", depends=["fetch"]))
    runs.handle_entry("4-0", fields("StepStarted", "running", step="load", depends=["fetch", "clean"]))

    dag = drawn(feed)
    assert edges(dag) == {"fetch": [], "clean": ["fetch"], "load": ["fetch", "clean"]}
    assert [step["status"] for step in dag["steps"]] == ["succeeded", "succeeded", "running"]
    Dag.model_validate(dag)


def test_a_step_reported_again_without_depends_keeps_the_edges_it_had() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepStarted", "running", step="load", depends=["fetch"]))

    runs.handle_entry("3-0", fields("StepFinished", "succeeded", step="load"))

    assert edges(drawn(feed))["load"] == ["fetch"]


def test_the_next_run_starts_every_known_step_over() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch"))

    runs.handle_entry("3-0", fields("StepStarted", "running", run="r2", at=START + 600))

    assert [(s["name"], s["status"]) for s in drawn(feed)["steps"]] == [("fetch", "not_started")]


def test_a_graph_learned_before_a_restart_is_drawn_after_it() -> None:
    history = HistoryStore("sqlite://", {})
    first = PushRuns(BoardFeed().runs(PUSHED_INSTANCE), history)
    first.handle_entry("1-0", fields("StepStarted", "running"))
    first.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch"))
    first.handle_entry("3-0", fields("StepFinished", "succeeded", step="clean", depends=["fetch"]))

    feed = BoardFeed()
    PushRuns(feed.runs(PUSHED_INSTANCE), history)

    assert drawn(feed) == {
        "name": "pushed/nightly",
        "status": "not_started",
        "runId": "",
        "startedAt": "",
        "finishedAt": "",
        "schedule": [],
        "stats": None,
        "rerun": None,
        "steps": [
            {
                "name": "fetch",
                "depends": [],
                "status": "not_started",
                "kind": None,
                "precondition": None,
                "lock": None,
                "last": [],
            },
            {
                "name": "clean",
                "depends": ["fetch"],
                "status": "not_started",
                "kind": None,
                "precondition": None,
                "lock": None,
                "last": [],
            },
        ],
    }


def test_a_pushed_workflow_serves_what_its_events_say_and_leaves_the_rest_absent() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch"))

    dag = drawn(feed)

    assert Dag.model_validate(dag).stats is None
    assert (dag["schedule"], dag["stats"]) == ([], None)
    assert [(s["precondition"], s["lock"], s["last"]) for s in dag["steps"]] == [(None, None, ["succeeded"])]


def test_a_step_keeps_its_last_outcomes_across_runs_newest_first() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch"))
    runs.handle_entry("3-0", fields("StepStarted", "running", run="r2", at=START + 600))
    runs.handle_entry("4-0", fields("StepFinished", "failed", step="fetch", run="r2", at=START + 601))
    runs.handle_entry("5-0", fields("StepStarted", "running", run="r3", at=START + 1200))

    assert drawn(feed)["steps"][0]["last"] == ["failed", "succeeded"]


def test_a_step_reported_twice_in_one_run_counts_once() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepFinished", "failed", step="fetch"))
    runs.handle_entry("3-0", fields("StepFinished", "succeeded", step="fetch", at=START + 1))

    assert drawn(feed)["steps"][0]["last"] == ["succeeded"]


def test_workflows_do_not_share_a_graph() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    for workflow in ("nightly", "weekly"):
        runs.handle_entry("1-0", fields("StepStarted", "running", workflow=workflow))
    runs.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch", workflow="nightly"))

    assert [s["name"] for s in drawn(feed, "nightly")["steps"]] == ["fetch"]
    assert drawn(feed, "weekly")["steps"] == []


def test_a_step_of_a_run_that_is_not_the_one_drawn_is_dropped() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running", run="r2"))

    runs.handle_entry("2-0", fields("StepFinished", "failed", run="r1", step="old"))

    assert drawn(feed)["steps"] == []


def test_an_entry_the_contract_does_not_allow_is_dropped() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    before = drawn(feed)

    runs.handle_entry("2-0", fields("StepFinished", "waiting"))
    runs.handle_entry("3-0", fields("StepFinished", "failed") | {"event": "pause"})
    runs.handle_entry("4-0", {"event": "StepFinished"})
    runs.handle_entry("5-0", fields("StepFinished", "failed", step="s") | {"depends": "fetch"})
    runs.handle_entry("6-0", fields("StepFinished", "failed", step="s") | {"depends": {"a": 1}})

    assert drawn(feed) == before


@pytest.mark.parametrize("depends", [[1, 2], "fetch", {"fetch": 1}, 7, '["fetch"]'])
def test_depends_that_is_not_a_list_of_step_names_drops_the_entry(depends: object) -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    before = drawn(feed)

    runs.handle_entry("2-0", fields("StepFinished", "failed", step="s") | {"depends": depends})

    assert drawn(feed) == before


def test_a_step_reported_again_takes_the_new_status_and_replaces_its_edges() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepStarted", "running", step="load", depends=["fetch"]))

    runs.handle_entry("3-0", fields("StepFinished", "failed", step="load", depends=["clean", "fetch"]))

    assert [(s["name"], s["status"], s["depends"]) for s in drawn(feed)["steps"]] == [
        ("load", "failed", ["clean", "fetch"])
    ]


def test_the_end_of_a_workflow_that_never_started_is_dropped() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))

    runs.handle_entry("1-0", fields("StepFinished", "failed"))

    assert feed.snapshot()["dags"] == []


def test_without_a_store_a_run_is_drawn_and_its_steps_are_not_kept() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), None)

    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepFinished", "succeeded", step="fetch"))

    assert edges(drawn(feed)) == {"fetch": []}


def _listed(name: str) -> dict:
    return {"name": name, "status": "succeeded", "runId": "", "startedAt": "", "finishedAt": "", "steps": []}


@pytest.mark.parametrize("listed_first", [True, False])
def test_a_workflow_an_adapter_lists_is_drawn_once_whichever_reads_the_stream_first(listed_first: bool) -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), None)

    def list_it() -> None:
        feed.set_dags("ci", [_listed("nightly")], None)

    def push_it() -> None:
        runs.handle_entry("1-0", fields("StepStarted", "running"))
        runs.handle_entry("2-0", fields("StepStarted", "running", workflow="other"))

    for step in (list_it, push_it) if listed_first else (push_it, list_it):
        step()

    assert sorted(dag["name"] for dag in feed.snapshot()["dags"]) == ["ci/nightly", f"{PUSHED_INSTANCE}/other"]


def test_a_workflow_an_adapter_lists_is_drawn_once_when_its_instance_pushes_it_too() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), None)
    feed.set_dags("dagu", [_listed("nightly")], None)

    runs.handle_entry("1-0", fields("StepStarted", "running", instance="dagu"))

    assert [dag["name"] for dag in feed.snapshot()["dags"]] == ["dagu/nightly"]


def test_a_step_reported_again_is_published_to_a_subscriber_that_saw_the_earlier_status() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepStarted", "running", step="load"))
    _, changes = feed.subscribe()

    runs.handle_entry("3-0", fields("StepFinished", "failed", step="load"))

    kind, data = changes.get_nowait()
    assert kind == "dags"
    assert [(s["name"], s["status"]) for s in data["dags"][0]["steps"]] == [("load", "failed")]


def test_pushed_runs_fed_from_the_event_log_draw_the_workflow_with_its_learned_steps(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    log._append(run_events.STREAM, fields("StepStarted", "running"))
    log._append(run_events.STREAM, fields("StepFinished", "succeeded", step="fetch"))
    log._append(run_events.STREAM, fields("StepStarted", "running", step="load", depends=["fetch"]))
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", {}))
    stop = threading.Event()

    follow(runs, log, run_events.STREAM, runs.handle_entry, stop=stop, interval=0.01)
    deadline = time.monotonic() + 5
    while not feed.snapshot()["dags"] or edges(drawn(feed)) != {"fetch": [], "load": ["fetch"]}:
        assert time.monotonic() < deadline, "the replayed entries never drew the workflow"
        time.sleep(0.01)
    stop.set()

    assert drawn(feed)["status"] == "running"


def test_an_entry_from_an_instance_is_its_own_workflow_beside_a_pushed_one_of_the_same_name() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))

    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepStarted", "failed", run="c1", instance="cron"))

    assert drawn(feed)["runId"] == "r1"
    assert drawn(feed, "cron/nightly")["runId"] == "c1"
    assert drawn(feed, "cron/nightly")["status"] == "failed"


def _kinds(changes: Any) -> list[str]:
    out = []
    while not changes.empty():
        out.append(changes.get_nowait()[0])
    return out


def test_the_startup_replay_publishes_the_workflows_once_when_it_reaches_the_last_entry() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    _, changes = feed.subscribe()
    runs.expect("3-0")

    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepStarted", "running", step="load"))
    assert _kinds(changes) == []

    runs.handle_entry("3-0", fields("StepFinished", "succeeded", step="load"))
    assert _kinds(changes) == ["dags"]
    assert [(s["name"], s["status"]) for s in drawn(feed)["steps"]] == [("load", "succeeded")]

    runs.handle_entry("4-0", fields("StepFinished", "succeeded", at=START + 60))
    assert _kinds(changes) == ["dags"]


def test_a_replay_whose_last_entry_is_dropped_still_publishes_what_it_read() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.expect("2-0")

    runs.handle_entry("1-0", fields("StepStarted", "running"))
    runs.handle_entry("2-0", fields("StepStarted", "running", run="r0", step="late"))

    assert drawn(feed)["status"] == "running"


def test_an_empty_stream_holds_nothing_back() -> None:
    feed = BoardFeed()
    runs = PushRuns(feed.runs(PUSHED_INSTANCE), HistoryStore("sqlite://", {}))
    runs.expect("0-0")

    runs.handle_entry("1-0", fields("StepStarted", "running"))

    assert drawn(feed)["status"] == "running"


def _wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met within the timeout"
        time.sleep(0.01)


class _Spy(PushRuns):
    """A `PushRuns` that notes the ids of the entries it is handed."""

    def __init__(self, *args: Any, handled: list[str]) -> None:
        super().__init__(*args)
        self._handled = handled

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        self._handled.append(entry_id)
        super().handle_entry(entry_id, fields)


def test_a_restarted_reader_resumes_from_its_saved_state_and_reads_only_the_entries_after_its_cursor(
    tmp_path: Path,
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    history = f"sqlite:///{tmp_path / 'history.sqlite'}"
    log._append(run_events.STREAM, fields("StepStarted", "running"))
    log._append(run_events.STREAM, fields("StepStarted", "running", step="load", depends=["fetch"]))
    log._append(run_events.STREAM, fields("StepFinished", "succeeded"))
    first, stop = BoardFeed(), threading.Event()
    runs = PushRuns(first.runs(PUSHED_INSTANCE), HistoryStore(history, {}))
    follow(runs, log, run_events.STREAM, runs.handle_entry, stop=stop, interval=0.01)
    _wait_until(lambda: first.snapshot()["dags"] and drawn(first)["status"] == "succeeded")
    stop.set()
    _wait_until(lambda: log.checkpoints.load(run_events.STREAM)[0] == 3)
    log._append(run_events.STREAM, fields("StepStarted", "running", run="r2", at=START + 60))

    handled: list[str] = []
    second, stop = BoardFeed(), threading.Event()
    restarted = _Spy(second.runs(PUSHED_INSTANCE), HistoryStore(history, {}), handled=handled)
    follow(restarted, log, run_events.STREAM, restarted.handle_entry, stop=stop, interval=0.01)
    _wait_until(lambda: second.snapshot()["dags"] and drawn(second)["runId"] == "r2")
    stop.set()

    assert handled == ["4"]
    assert edges(drawn(second)) == {"load": ["fetch"]}


def test_a_restart_with_nothing_new_draws_the_saved_workflows_without_reading_an_entry(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    log._append(run_events.STREAM, fields("StepStarted", "running"))
    first = PushRuns(BoardFeed().runs(PUSHED_INSTANCE), None)
    first.resume(log.checkpoints, run_events.STREAM, lambda cursor: True)
    first.handle_entry("1-0", fields("StepStarted", "running"))
    first.save()

    handled: list[str] = []
    feed, stop = BoardFeed(), threading.Event()
    restarted = _Spy(feed.runs(PUSHED_INSTANCE), None, handled=handled)
    follow(restarted, log, run_events.STREAM, restarted.handle_entry, stop=stop, interval=0.01)
    _wait_until(lambda: feed.snapshot()["dags"])
    stop.set()

    assert drawn(feed)["status"] == "running"
    assert handled == []


@pytest.mark.parametrize("saved", [(None, None), (1, None)])
def test_a_reader_with_no_usable_saved_state_replays_the_retention(saved: tuple[int | None, None]) -> None:
    class Store:
        def load(self, stream: str, model: type[PushedRunsSnapshot]) -> tuple[int | None, None]:
            return saved

        def save(self, stream: str, position: int, model: PushedRunsSnapshot, *, conn: object = None) -> None: ...

    runs = PushRuns(BoardFeed().runs(PUSHED_INSTANCE), None)

    assert runs.resume(Store(), run_events.STREAM, lambda cursor: True) is None


def test_a_reader_whose_saved_cursor_the_log_no_longer_retains_replays_the_retention() -> None:
    class Store:
        def load(self, stream: str, model: type[PushedRunsSnapshot]) -> tuple[int, PushedRunsSnapshot]:
            return 1, PushedRunsSnapshot(dags={})

    runs = PushRuns(BoardFeed().runs(PUSHED_INSTANCE), None)

    assert runs.resume(Store(), run_events.STREAM, lambda cursor: False) is None
