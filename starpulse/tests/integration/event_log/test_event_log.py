"""The event log across processes: a second process's append reaches a running tail."""

import ast
import multiprocessing
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import event, select, text, update

import starpulse
from starpulse.event_log.event_log import Entry, EventLog, Tail, prune_forever
from starpulse.event_log.tables import events, gaps


def _append(url: str, event: str) -> int | None:
    return EventLog(url)._append("machine:events", {"event": event})


@pytest.fixture(scope="module")
def processes() -> Iterator[ProcessPoolExecutor]:
    """A new process for each append, forked from a server that imported the event log once: a new interpreter
    importing it for each append was most of what these tests waited on."""
    context = multiprocessing.get_context("forkserver")
    context.set_forkserver_preload([__name__])
    with ProcessPoolExecutor(6, mp_context=context, max_tasks_per_child=1) as pool:
        yield pool


def test_one_poll_reads_what_another_process_appended(database_url: str, processes: ProcessPoolExecutor) -> None:
    tail = Tail.replay(EventLog(database_url), "machine:events")
    assert tail.poll() == []

    cursor = processes.submit(_append, database_url, "FIRST").result()

    assert [(e.id, e.fields["event"]) for e in tail.poll()] == [(cursor, "FIRST")]


def test_an_idle_poll_reads_the_oldest_and_newest_id_without_scanning_the_table(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        pytest.skip("the query plan asserted is SQLite's")
    log = EventLog(database_url)
    log._append("machine:events", {"event": "FIRST"})
    tail = Tail.replay(log, "machine:events")
    tail.poll()
    statements: list[str] = []
    event.listen(log.engine, "before_cursor_execute", lambda conn, cur, stmt, *rest: statements.append(stmt))

    assert tail.poll() == []

    with log.engine.connect() as db:
        plan = [row[-1] for row in db.execute(text(f"EXPLAIN QUERY PLAN {statements[0]}"))]
    assert not [step for step in plan if step.startswith("SCAN starpulse_events")], plan


def test_a_running_tail_hands_over_what_another_process_appends(
    database_url: str, processes: ProcessPoolExecutor
) -> None:
    seen: list[Entry] = []
    arrived = threading.Event()

    def handle(entry: Entry) -> None:
        seen.append(entry)
        arrived.set()

    stop = threading.Event()
    reader = threading.Thread(
        target=Tail.replay(EventLog(database_url), "machine:events", interval=0.05).run, args=(handle, stop)
    )
    reader.start()
    try:
        processes.submit(_append, database_url, "LATER").result()
        assert arrived.wait(timeout=5)
    finally:
        stop.set()
        reader.join(timeout=5)

    assert [e.fields["event"] for e in seen] == ["LATER"]


def test_appends_from_several_processes_are_all_read_once_in_cursor_order(
    database_url: str, processes: ProcessPoolExecutor
) -> None:
    appends = [processes.submit(_append, database_url, f"E{i}") for i in range(6)]
    for append in appends:
        append.result()

    entries = Tail.replay(EventLog(database_url), "machine:events").poll()

    assert sorted(e.fields["event"] for e in entries) == [f"E{i}" for i in range(6)]
    assert [e.id for e in entries] == sorted(e.id for e in entries)


def test_a_reader_left_behind_by_the_prune_timer_records_a_gap(database_url: str, tmp_path: Path) -> None:
    log = EventLog(database_url)
    for n in range(1, 5):
        log._append("machine:events", {"n": n})
    reader = Tail.replay(log, "machine:events")
    assert [e.id for e in reader.poll()] == [1, 2, 3, 4]
    for n in range(5, 8):
        log._append("machine:events", {"n": n})
    with log.engine.begin() as db:  # rows 1 to 5 are 10 days old; the reader's cursor is row 1, so 2 to 5 go unread
        db.execute(update(events).where(events.c.id.between(1, 5)).values(at=time.time() - 10 * 86400))
    reader.cursor = 1

    stop = threading.Event()
    timer = threading.Thread(
        target=prune_forever,
        args=(log,),
        kwargs={"retention_days": 7, "archive_dir": tmp_path / "archive", "stop": stop},
    )
    timer.start()
    try:
        deadline = time.monotonic() + 10
        while log.oldest() != 6 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop.set()
        timer.join()

    assert [e.id for e in reader.poll()] == [6, 7]
    with log.engine.connect() as db:
        gaps_ = [tuple(r) for r in db.execute(select(gaps.c.stream, gaps.c.after_id, gaps.c.before_id, gaps.c.lost))]
    assert gaps_ == [("machine:events", "1", "6", 4)]


#: The readers that built a `Tail` themselves, which the event log's catch-up boundary is to serve instead.
_FORMER_TAIL_CALLERS = (
    "event_log/lane_events.py",
    "event_log/conformance_monitor.py",
    "_internal/runs/projection.py",
    "flow_metrics/history.py",
)


def _tail_constructions(path: Path) -> list[int]:
    """The line of each `Tail.replay(...)` call in `path`, found in its syntax tree so a comment or docstring is not one."""
    calls = [node for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Call)]
    named = [
        call for call in calls if getattr(call.func, "id", None) == "Tail" or getattr(call.func, "attr", None) == "Tail"
    ]
    return sorted(call.lineno for call in named)


def test_no_reader_outside_the_event_log_constructs_a_tail_itself() -> None:
    root = Path(next(iter(starpulse.__path__)))

    constructed = {name: _tail_constructions(root / name) for name in _FORMER_TAIL_CALLERS}

    assert {name: lines for name, lines in constructed.items() if lines} == {}
