"""The event log across processes, on SQLite and on Postgres: a second process's append reaches a running tail."""

import subprocess
import sys
import threading
from pathlib import Path

from starpulse.event_log import Entry, EventLog, Tail

_APPEND = (
    "import sys; from starpulse.event_log import EventLog; "
    "print(EventLog(sys.argv[1]).append('machine:events', {'event': sys.argv[2]}))"
)


def _append_in_another_process(url: str, event: str) -> int | None:
    done = subprocess.run([sys.executable, "-c", _APPEND, url, event], capture_output=True, text=True, check=True)
    return None if done.stdout.strip() == "None" else int(done.stdout)


def test_one_poll_reads_what_another_process_appended(database_url: str) -> None:
    tail = Tail(EventLog(database_url), "machine:events")
    assert tail.poll() == []

    cursor = _append_in_another_process(database_url, "FIRST")

    assert [(e.id, e.fields["event"]) for e in tail.poll()] == [(cursor, "FIRST")]


def test_a_running_tail_hands_over_what_another_process_appends(database_url: str) -> None:
    seen: list[Entry] = []
    arrived = threading.Event()

    def handle(entry: Entry) -> None:
        seen.append(entry)
        arrived.set()

    stop = threading.Event()
    reader = threading.Thread(
        target=Tail(EventLog(database_url), "machine:events", interval=0.05).run, args=(handle, stop)
    )
    reader.start()
    try:
        _append_in_another_process(database_url, "LATER")
        assert arrived.wait(timeout=5)
    finally:
        stop.set()
        reader.join(timeout=5)

    assert [e.fields["event"] for e in seen] == ["LATER"]


def test_appends_from_several_processes_are_all_read_once_in_cursor_order(database_url: str) -> None:
    processes = [
        subprocess.Popen([sys.executable, "-c", _APPEND, database_url, f"E{i}"], stdout=subprocess.PIPE, text=True)
        for i in range(6)
    ]
    for process in processes:
        process.communicate()
        assert process.returncode == 0

    entries = Tail(EventLog(database_url), "machine:events").poll()

    assert sorted(e.fields["event"] for e in entries) == [f"E{i}" for i in range(6)]
    assert [e.id for e in entries] == sorted(e.id for e in entries)


def test_starpulse_emit_in_another_process_reaches_the_tail_of_the_database_the_config_names(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'store.sqlite'}"
    config = tmp_path / "view.toml"
    config.write_text(f'database_url = "{database}"\n')
    tail = Tail(EventLog(database), "runs:events")
    assert tail.poll() == []

    subprocess.run(
        [sys.executable, "-m", "starpulse", "emit", "start", "--workflow", "nightly", "--run", "r1",
         "--status", "running", "--config", str(config)],
        cwd=tmp_path, capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip

    assert [(e.fields["workflow"], e.fields["run_id"], e.fields["status"]) for e in tail.poll()] == [
        ("nightly", "r1", "running")
    ]
