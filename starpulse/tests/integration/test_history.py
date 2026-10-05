"""The history store's rules, on SQLite and on Postgres, and its recorder fed from a real Redis."""

import re
import threading

import pytest
import redis as redis_lib
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from starpulse import events
from starpulse.history import HistoryStore, build_machine_recorder
from starpulse.streams import StreamConsumer, StreamProducer
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
        {"at": 0.0, "from": None, "to": "Ready"},
        {"at": 2.0, "from": "Ready", "to": "Doing"},
        {"at": 3.0, "from": "Doing", "to": "Ready"},
    ]
    assert store.lane_path("PROJ-404") == []


def test_a_late_arriving_lane_change_is_placed_by_its_time_and_the_next_compares_with_the_newest(
    store: HistoryStore,
) -> None:
    store.record_lane("a", "PROJ-7", "Ready", 5.0)
    store.record_lane("b", "PROJ-7", "Doing", 3.0)  # observed after "a" but older
    store.record_lane("c", "PROJ-7", "Doing", 9.0)  # the newest lane is "a"'s Ready, so this is a change

    assert store.lane_path("PROJ-7") == [
        {"at": 3.0, "from": "Ready", "to": "Doing"},
        {"at": 5.0, "from": None, "to": "Ready"},
        {"at": 9.0, "from": "Ready", "to": "Doing"},
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
        ("PROJ-8", 1.0, None, "To Do"),
        ("PROJ-7", 5.0, None, "Ready"),
        ("PROJ-7", 9.0, "Ready", "Done"),
    ]


def test_the_same_gap_reported_again_is_one_gap_with_its_latest_bounds(store: HistoryStore) -> None:
    store.record_gap("machine:events", "5-0", "9-0", 3)
    store.record_gap("machine:events", "5-0", "12-0", 6)
    store.record_gap("board:events", "5-0", "7-0", 1)

    assert store.gaps() == [
        {"stream": "machine:events", "after_id": "5-0", "before_id": "12-0", "lost": 6},
        {"stream": "board:events", "after_id": "5-0", "before_id": "7-0", "lost": 1},
    ]


def test_each_database_has_its_own_consumer_group(store: HistoryStore, tmp_path) -> None:
    url = store.engine.url.render_as_string(hide_password=False)
    other = HistoryStore(f"sqlite:///{tmp_path / 'other.sqlite'}", MACHINES)

    assert re.fullmatch(r"starpulse-history-[0-9a-f]{8}", store.group)
    assert other.group != store.group
    assert HistoryStore(url, MACHINES, engine=store.engine).group == store.group


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


def test_the_recorder_reads_machine_events_on_its_own_redis_through_the_stores_group(
    store: HistoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{events.REDIS_ENV_PREFIX}_REDIS_HOST", "redis.example")
    monkeypatch.setenv(f"{events.REDIS_ENV_PREFIX}_REDIS_PORT", "6400")

    recorder = build_machine_recorder(store)
    recorder.on_gap("5-0", "9-0", 3)
    recorder.handler("7-0", {k: v for k, v in _CLAIM.items() if k != "event_id"})

    assert (recorder.redis_host, recorder.redis_port) == ("redis.example", 6400)
    assert (recorder.stream, recorder.group, recorder.consumer) == (events.STREAM, store.group, store.group)
    assert recorder.transient == (OperationalError,)  # an unreachable database leaves the entry pending
    assert store.gaps() == [{"stream": events.STREAM, "after_id": "5-0", "before_id": "9-0", "lost": 3}]
    assert _event_ids(store) == ["7-0"]


def _send(client: redis_lib.Redis, event: str, at: float, task: str = "PROJ-7") -> str:
    producer = StreamProducer(stream=events.STREAM, client_factory=lambda: client)
    entry_id = events.publish("in-progress", event, actor="agent", task=task, now=at, producer=producer)
    assert entry_id is not None
    return entry_id


def _recorder(store: HistoryStore) -> StreamConsumer:
    recorder = build_machine_recorder(store)
    recorder.read_block_ms = 100
    return recorder


def test_a_trim_past_an_unconsumed_entry_is_recorded_as_a_gap_with_its_id_range(
    redis_client: redis_lib.Redis, store: HistoryStore
) -> None:
    first = _send(redis_client, "WORKTREE_READY", 100.0)
    read = _send(redis_client, "RED_PROVEN", 101.0)
    _recorder(store).consume_once(redis_client)  # the consumer runs, then stops

    lost_a = _send(redis_client, "GREEN", 102.0)
    lost_b = _send(redis_client, "AC_CHECKPOINTED", 103.0)
    kept = _send(redis_client, "DOCS_RECONCILED", 104.0)
    redis_client.xtrim(events.STREAM, maxlen=1, approximate=False)  # while it is down
    assert [entry_id for entry_id, _ in redis_client.xrange(events.STREAM) or []] == [kept]

    _recorder(store).consume_once(redis_client)  # restarts

    assert store.gaps() == [{"stream": events.STREAM, "after_id": read, "before_id": kept, "lost": 2}]
    assert first < read < lost_a < lost_b < kept
    assert len(_event_ids(store)) == 3  # the two it read and the one the stream kept


def test_every_event_written_while_the_consumer_runs_has_exactly_one_row_after_the_trim(
    redis_client: redis_lib.Redis, store: HistoryStore
) -> None:
    recorder = _recorder(store)
    sent = []
    for i in range(6):
        sent.append(_send(redis_client, "AC_CHECKPOINTED", 100.0 + i, task=f"PROJ-{i % 2}"))
        recorder.consume_once(redis_client)
        redis_client.xtrim(events.STREAM, maxlen=1, approximate=False)
    _recorder(store).consume_once(redis_client)  # a restart redelivers nothing and adds nothing

    assert redis_client.xlen(events.STREAM) == 1
    assert sorted(_event_ids(store)) == sorted(set(_event_ids(store))) and len(_event_ids(store)) == len(sent) == 6
    assert store.gaps() == []


def test_a_trim_that_empties_the_stream_is_a_gap_up_to_the_id_after_the_newest_entry(
    redis_client: redis_lib.Redis, store: HistoryStore
) -> None:
    _send(redis_client, "WORKTREE_READY", 100.0)
    read = _send(redis_client, "RED_PROVEN", 101.0)
    _recorder(store).consume_once(redis_client)
    _send(redis_client, "GREEN", 102.0)
    newest = _send(redis_client, "AC_CHECKPOINTED", 103.0)
    redis_client.xtrim(events.STREAM, maxlen=0, approximate=False)
    millis, _, sequence = newest.partition("-")

    _recorder(store).consume_once(redis_client)

    assert store.gaps() == [
        {"stream": events.STREAM, "after_id": read, "before_id": f"{millis}-{int(sequence) + 1}", "lost": 2}
    ]


def test_a_consumer_over_a_stream_that_does_not_exist_yet_records_no_gap(
    redis_client: redis_lib.Redis, store: HistoryStore
) -> None:
    _recorder(store).consume_once(redis_client)

    assert (store.gaps(), _event_ids(store)) == ([], [])


def test_a_group_that_never_read_reports_no_gap_for_what_was_trimmed_before_it_started(
    redis_client: redis_lib.Redis, store: HistoryStore
) -> None:
    _send(redis_client, "WORKTREE_READY", 100.0)
    _send(redis_client, "RED_PROVEN", 101.0)
    redis_client.xtrim(events.STREAM, maxlen=1, approximate=False)

    _recorder(store).consume_once(redis_client)

    assert (store.gaps(), len(_event_ids(store))) == ([], 1)


def test_a_single_lost_entry_is_a_gap_of_one(redis_client: redis_lib.Redis, store: HistoryStore) -> None:
    read = _send(redis_client, "WORKTREE_READY", 100.0)
    _recorder(store).consume_once(redis_client)
    _send(redis_client, "RED_PROVEN", 101.0)
    kept = _send(redis_client, "GREEN", 102.0)
    redis_client.xtrim(events.STREAM, maxlen=1, approximate=False)

    _recorder(store).consume_once(redis_client)

    assert store.gaps() == [{"stream": events.STREAM, "after_id": read, "before_id": kept, "lost": 1}]


def test_a_trim_after_the_consumer_read_everything_is_not_a_gap(
    redis_client: redis_lib.Redis, store: HistoryStore
) -> None:
    _send(redis_client, "WORKTREE_READY", 100.0)
    _send(redis_client, "RED_PROVEN", 101.0)
    _recorder(store).consume_once(redis_client)
    redis_client.xtrim(events.STREAM, maxlen=0, approximate=False)  # nothing it had not read was lost

    _recorder(store).consume_once(redis_client)

    assert store.gaps() == []
