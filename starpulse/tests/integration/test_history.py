"""The history store's rules, on SQLite and on Postgres, and its recorder fed from the event log."""

import threading
import time
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from starpulse._internal.domain.level_metrics import UNATTRIBUTED, Run
from starpulse._internal.store import events
from starpulse._internal.store.event_log import EventLog
from starpulse._internal.store.history import HistoryStore, record_machine_events
from starpulse._internal.store.tables import metadata
from starpulse.tests.machines import MACHINES

_CLAIM = {"event_id": "e-1", "machine": "in-progress", "event": "WORKTREE_READY", "task": "PROJ-7", "time": "100"}
_RUN = {"event_id": "r-1", "machine": "authoring-skills", "event": "GUIDANCE_READ", "run": "run-1", "time": "5"}


def _event_ids(store: HistoryStore) -> list[str]:
    with store.engine.connect() as db:
        return [row[0] for row in db.execute(text("SELECT event_id FROM starpulse_machine_events ORDER BY id"))]


def test_a_redelivered_machine_entry_is_one_row(store: HistoryStore) -> None:
    store.record_machine("1-0", _CLAIM)
    store.record_machine("2-0", _CLAIM)  # the producer re-sent the same event under a new stream id

    assert _event_ids(store) == ["e-1"]


def test_an_entry_without_an_event_id_is_keyed_by_its_stream_id(store: HistoryStore) -> None:
    fields = {k: v for k, v in _CLAIM.items() if k != "event_id"}
    store.record_machine("1-0", fields)
    store.record_machine("1-0", fields)
    store.record_machine("2-0", fields)

    assert _event_ids(store) == ["1-0", "2-0"]


def test_a_run_keyed_entry_is_kept_with_its_run_and_actor_but_has_no_task_path(store: HistoryStore) -> None:
    store.record_machine("1-0", _RUN | {"actor": "dispatcher"})

    with store.engine.connect() as db:
        row = db.execute(
            text("SELECT event_id, task, run, machine, event, actor, occurred_at FROM starpulse_machine_events")
        ).one()

    assert tuple(row) == ("r-1", None, "run-1", "authoring-skills", "GUIDANCE_READ", "dispatcher", 5.0)
    assert store.machine_path("run-1", "authoring-skills") == ([], 0)


def test_a_tasks_machine_path_places_each_event_and_counts_every_row(store: HistoryStore) -> None:
    for i, event in enumerate(["WORKTREE_READY", "NOT_AN_EVENT", "RED_PROVEN"]):
        store.record_machine(f"{i}-0", _CLAIM | {"event_id": f"e{i}", "event": event, "time": str(100 + i)})

    assert store.machine_path("PROJ-7", "in-progress") == (
        [
            {"at": 100.0, "event": "WORKTREE_READY", "state": "worktree_ready"},
            {"at": 101.0, "event": "NOT_AN_EVENT", "state": "worktree_ready"},
            {"at": 102.0, "event": "RED_PROVEN", "state": "red_proven"},
        ],
        3,
    )
    assert store.machine_path("PROJ-404", "in-progress") == ([], 0)


def test_a_status_that_repeats_the_tasks_last_adds_no_lane_change(store: HistoryStore) -> None:
    for at, (status, event_id) in enumerate((("Ready", "a"), ("Ready", "b"), ("Doing", "c"), ("Ready", "d"))):
        store.record_lane(event_id, "PROJ-7", status, float(at))
    store.record_lane("a", "PROJ-7", "Done", 9.0)  # a redelivered event id is no change

    assert store.lane_path("PROJ-7") == [
        {"at": 0.0, "from": None, "to": "ready"},
        {"at": 2.0, "from": "ready", "to": "doing"},
        {"at": 3.0, "from": "doing", "to": "ready"},
    ]
    assert store.lane_path("PROJ-404") == []


def test_a_late_arriving_lane_change_is_placed_by_its_time_and_the_next_compares_with_the_newest(
    store: HistoryStore,
) -> None:
    store.record_lane("a", "PROJ-7", "Ready", 5.0)
    store.record_lane("b", "PROJ-7", "Doing", 3.0)  # observed after "a" but older
    store.record_lane("c", "PROJ-7", "Doing", 9.0)  # the newest lane is "a"'s Ready, so this is a change

    assert store.lane_path("PROJ-7") == [
        {"at": 3.0, "from": "ready", "to": "doing"},
        {"at": 5.0, "from": None, "to": "ready"},
        {"at": 9.0, "from": "ready", "to": "doing"},
    ]


def test_a_machine_path_is_ordered_by_time_and_holds_only_that_machines_events(store: HistoryStore) -> None:
    store.record_machine("1-0", _CLAIM | {"event_id": "e1", "event": "RED_PROVEN", "time": "102"})
    store.record_machine("2-0", _CLAIM | {"event_id": "e2", "event": "WORKTREE_READY", "time": "100"})
    store.record_machine("3-0", _CLAIM | {"event_id": "e3", "machine": "pull-request", "event": "PUSHED"})

    assert store.machine_path("PROJ-7", "in-progress") == (
        [
            {"at": 100.0, "event": "WORKTREE_READY", "state": "worktree_ready"},
            {"at": 102.0, "event": "RED_PROVEN", "state": "red_proven"},
        ],
        2,
    )


def test_lane_rows_are_every_tasks_lane_changes_in_time_order(store: HistoryStore) -> None:
    store.record_lane("a", "PROJ-7", "Ready", 5.0)
    store.record_lane("b", "PROJ-8", "To Do", 1.0)
    store.record_lane("c", "PROJ-7", "Ready", 6.0)  # repeats the last lane: no change
    store.record_lane("d", "PROJ-7", "Done", 9.0)

    assert store.lane_rows() == [
        ("PROJ-8", 1.0, None, "to_do"),
        ("PROJ-7", 5.0, None, "ready"),
        ("PROJ-7", 9.0, "ready", "done"),
    ]


def test_the_same_gap_reported_again_is_one_gap_with_its_latest_bounds(store: HistoryStore) -> None:
    store.record_gap("machine:events", "5-0", "9-0", 3)
    store.record_gap("machine:events", "5-0", "12-0", 6)
    store.record_gap("board:events", "5-0", "7-0", 1)

    assert store.gaps() == [
        {"stream": "machine:events", "after_id": "5-0", "before_id": "12-0", "lost": 6},
        {"stream": "board:events", "after_id": "5-0", "before_id": "7-0", "lost": 1},
    ]


def test_a_store_holds_a_cursor_per_stream_which_a_store_opened_again_reads(store: HistoryStore) -> None:
    assert store.cursor("machine:events") is None

    store.record_machine("1-0", _CLAIM, cursor=7)
    store.record_machine("2-0", _CLAIM | {"event_id": "e-2"}, cursor=9)
    url = store.engine.url.render_as_string(hide_password=False)

    assert HistoryStore(url, MACHINES, engine=store.engine).cursor(events.STREAM) == 9
    assert store.cursor("board:events") is None


def test_a_reader_saves_its_own_cursor_and_a_later_save_replaces_it(store: HistoryStore) -> None:
    store.save_cursor("forward:https://hub.test", 12)
    store.save_cursor("forward:https://hub.test", 40)

    assert store.cursor("forward:https://hub.test") == 40
    assert store.cursor(events.STREAM) is None


def test_an_entry_that_cannot_be_written_moves_no_cursor(store: HistoryStore) -> None:
    store.record_machine("1-0", _CLAIM, cursor=3)

    with pytest.raises(KeyError):
        store.record_machine("2-0", {"event_id": "e-2"}, cursor=4)  # lacks the machine and event

    assert store.cursor(events.STREAM) == 3


def test_a_store_that_loses_the_race_to_create_the_tables_to_a_reader_thread_still_opens(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_all, attempts = metadata.create_all, []

    def lose_the_race(engine, **kwargs) -> None:
        attempts.append(1)
        create_all(engine, **kwargs)  # the log's reader created them meanwhile ...
        if len(attempts) == 1:
            raise OperationalError("CREATE TABLE starpulse_events", {}, Exception("table already exists"))

    monkeypatch.setattr(metadata, "create_all", lose_the_race)

    opened = HistoryStore(f"sqlite:///{tmp_path / 'raced.sqlite'}", MACHINES)

    assert (len(attempts), opened.cursor(events.STREAM)) == (2, None)


def test_a_thread_other_than_the_one_that_opened_the_store_can_use_it(store: HistoryStore) -> None:
    failures: list[BaseException] = []

    def work() -> None:
        try:
            store.record_machine("1-0", _CLAIM)
            store.record_gap("machine:events", "1-0", "5-0", 2)
            store.gaps()
        except Exception as exc:  # SQLite refuses a connection used off its creating thread
            failures.append(exc)

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()

    assert (failures, _event_ids(store)) == ([], ["e-1"])


def test_learned_steps_keep_their_order_and_edges_in_a_store_opened_again(store: HistoryStore) -> None:
    store.record_step("nightly", "fetch", None)
    store.record_step("nightly", "load", ["fetch"])
    store.record_step("weekly", "report", None)
    url = store.engine.url.render_as_string(hide_password=False)

    assert HistoryStore(url, MACHINES, engine=store.engine).learned_graphs() == {
        "nightly": {"fetch": [], "load": ["fetch"]},
        "weekly": {"report": []},
    }


def test_a_step_reported_without_depends_keeps_its_edges_and_one_with_them_replaces_them(store: HistoryStore) -> None:
    store.record_step("nightly", "load", ["fetch"])

    store.record_step("nightly", "load", None)
    assert store.learned_graphs() == {"nightly": {"load": ["fetch"]}}

    store.record_step("nightly", "load", ["clean"])
    assert store.learned_graphs() == {"nightly": {"load": ["clean"]}}


@pytest.fixture
def log(store: HistoryStore) -> EventLog:
    return EventLog(store.engine.url.render_as_string(hide_password=False), engine=store.engine)


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while not done():
        assert time.monotonic() < deadline, "the recorder never got there"
        time.sleep(0.01)


def _record(store: HistoryStore, log: EventLog, stop: threading.Event) -> threading.Thread:
    thread = threading.Thread(
        target=record_machine_events, args=(store, log, stop), kwargs={"interval": 0.01}, daemon=True
    )
    thread.start()
    return thread


def _emit(log: EventLog, event: str, at: float, task: str = "PROJ-7") -> int:
    cursor = log.append(
        events.STREAM, {"machine": "in-progress", "event": event, "task": task, "actor": "agent", "time": at}
    )
    assert cursor is not None
    return cursor


def _prune_below(log: EventLog, kept: int) -> None:
    """What a retention prune does: drop the oldest rows, here everything before `kept`."""
    with log.engine.begin() as db:
        db.execute(text("DELETE FROM starpulse_events WHERE id < :kept"), {"kept": kept})


def _stop(stop: threading.Event, thread: threading.Thread) -> None:
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_the_recorder_copies_the_logs_machine_events_into_the_store_and_keeps_its_cursor(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    _emit(log, "WORKTREE_READY", 100.0)
    log.append("board:events", {"machine": "in-progress", "event": "OTHER", "task": "PROJ-7", "time": 1})
    thread = _record(store, log, stop)
    newest = _emit(log, "RED_PROVEN", 101.0)  # appended while it runs
    _until(lambda: store.cursor(events.STREAM) == newest)
    _stop(stop, thread)

    assert [step["event"] for step in store.machine_path("PROJ-7", "in-progress")[0]] == [
        "WORKTREE_READY",
        "RED_PROVEN",
    ]
    assert len(_event_ids(store)) == 2  # keyed by the log's event ids, which the events were minted
    assert store.gaps() == []


def test_a_recorder_started_again_resumes_after_its_cursor_and_adds_nothing_twice(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    _emit(log, "WORKTREE_READY", 100.0)
    read = _emit(log, "RED_PROVEN", 101.0)
    first = _record(store, log, stop)
    _until(lambda: store.cursor(events.STREAM) == read)
    _stop(stop, first)

    again = threading.Event()
    last = _emit(log, "GREEN", 102.0)
    second = _record(store, log, again)
    _until(lambda: store.cursor(events.STREAM) == last)
    _stop(again, second)

    assert len(_event_ids(store)) == 3
    assert store.gaps() == []


def test_a_prune_past_an_unrecorded_entry_is_a_gap_with_its_id_range(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    _emit(log, "WORKTREE_READY", 100.0)
    read = _emit(log, "RED_PROVEN", 101.0)
    first = _record(store, log, stop)
    _until(lambda: store.cursor(events.STREAM) == read)
    _stop(stop, first)

    _emit(log, "GREEN", 102.0)
    _emit(log, "AC_CHECKPOINTED", 103.0)
    kept = _emit(log, "DOCS_RECONCILED", 104.0)
    _prune_below(log, kept)  # while it is down

    again = threading.Event()
    second = _record(store, log, again)
    _until(lambda: store.cursor(events.STREAM) == kept)
    _stop(again, second)

    assert store.gaps() == [{"stream": events.STREAM, "after_id": str(read), "before_id": str(kept), "lost": 2}]
    assert len(_event_ids(store)) == 3  # the two it read and the one the log kept


def test_a_store_with_no_cursor_replays_the_retained_log_and_reports_no_gap_for_what_was_pruned_before(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    _emit(log, "WORKTREE_READY", 100.0)
    _emit(log, "RED_PROVEN", 101.0)
    kept = _emit(log, "GREEN", 102.0)
    _prune_below(log, kept)

    thread = _record(store, log, stop)
    _until(lambda: store.cursor(events.STREAM) == kept)
    _stop(stop, thread)

    assert (store.gaps(), len(_event_ids(store))) == ([], 1)


def test_a_database_that_cannot_be_reached_leaves_the_entry_to_be_recorded_on_the_next_poll(
    store: HistoryStore, log: EventLog, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    write, failures = store.record_machine, []

    def flaky(event_id: str, fields: dict, **kwargs) -> None:
        if not failures:
            failures.append(event_id)
            raise OperationalError("insert", {}, Exception("connection refused"))
        write(event_id, fields, **kwargs)

    monkeypatch.setattr(store, "record_machine", flaky)
    only = _emit(log, "WORKTREE_READY", 100.0)

    thread = _record(store, log, stop)
    _until(lambda: store.cursor(events.STREAM) == only)
    _stop(stop, thread)

    assert (len(failures), len(_event_ids(store))) == (1, 1)


def test_board_level_runs_are_each_sources_tasks_lane_by_lane_with_the_lane_read_as_its_state(
    store: HistoryStore,
) -> None:
    store.record_lane("a/1", "T-1", "To Do", 1.0)
    store.record_lane("a/2", "T-1", "In Progress", 5.0)
    store.record_lane("a/3", "T-1", "Elsewhere", 6.0)  # no state of the Board machine
    store.record_lane("a/4", "T-1", "Done", 9.0)
    store.record_lane("b/1", "T-2", "ready", 2.0)  # a lane named by its state's id
    store.record_lane("local-1", "T-3", "To Do", 3.0)  # no source prefix: no forwarder named it

    assert sorted(store.level_runs("board"), key=lambda run: run.task) == [
        Run("a", "T-1", ((1.0, "to_do"), (5.0, "in_progress"), (9.0, "done"))),
        Run("b", "T-2", ((2.0, "ready"),)),
        Run(UNATTRIBUTED, "T-3", ((3.0, "to_do"),)),
    ]


def test_level_runs_of_another_machine_place_each_tasks_events_and_skip_runs_with_no_task(store: HistoryStore) -> None:
    store.record_machine("1-0", _CLAIM | {"event_id": "a/e1", "event": "WORKTREE_READY", "time": "100"})
    store.record_machine("2-0", _CLAIM | {"event_id": "a/e2", "event": "RED_PROVEN", "time": "102"})
    store.record_machine("3-0", _CLAIM | {"event_id": "e3", "event": "WORKTREE_READY", "time": "101", "task": "PROJ-8"})
    store.record_machine("4-0", _RUN | {"machine": "in-progress", "event_id": "a/r1"})  # keyed by run, not task
    store.record_machine("5-0", _CLAIM | {"event_id": "a/e5", "machine": "pull-request", "event": "PUSHED"})

    assert sorted(store.level_runs("in-progress"), key=lambda run: run.task) == [
        Run("a", "PROJ-7", ((100.0, "worktree_ready"), (102.0, "red_proven"))),
        Run(UNATTRIBUTED, "PROJ-8", ((101.0, "worktree_ready"),)),
    ]


def test_the_summaries_a_store_keeps_on_write_match_the_ones_folded_from_its_rows(store: HistoryStore) -> None:
    store.record_machine("1-0", _CLAIM)
    store.record_machine("2-0", _CLAIM)  # redelivered: counted once
    store.record_machine("3-0", _CLAIM | {"event_id": "e-2", "event": "RED_PROVEN", "time": "130"})
    store.record_machine("4-0", _RUN)
    store.record_lane("L-1", "PROJ-7", "Ready", 90.0)
    store.record_lane("L-2", "PROJ-7", "In Progress", 95.0)

    assert store.summary_differences() == []
    with store.engine.connect() as db:
        steps = db.execute(text("SELECT sum(steps) FROM starpulse_step_summaries")).scalar()
        open_stays = db.execute(text("SELECT lane FROM starpulse_lane_intervals WHERE left_at IS NULL")).scalars().all()
    assert steps == 5
    assert open_stays == ["in_progress"]
