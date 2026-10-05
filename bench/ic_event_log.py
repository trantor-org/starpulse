"""IC event log benchmark: concurrent fail-open appends to a SQLite WAL log while a reader polls by cursor.

Measures the instance-side event log under the load a busy instance puts on it.
Each append opens a fresh connection, as a short-lived
``starpulse emit`` does.

Run this file with ``uv run python``, passing a scratch SQLite path, which it
replaces.
"""

import json
import multiprocessing as mp
import sqlite3
import sys
import time
import uuid
from multiprocessing.synchronize import Event
from pathlib import Path

FIELDS = json.dumps(
    {
        "machine": "board",
        "event": "START",
        "task": "TASK-1234",
        "actor": "agent",
        "at": "2026-10-04T19:00:00-07:00",
        "pad": "x" * 60,
    }
)
INSERT = "INSERT INTO starpulse_events(stream, event_id, fields, at) VALUES (?, ?, ?, ?)"
WRITERS, APPENDS = 8, 250


def connect(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=5, isolation_level=None)
    c.execute("pragma journal_mode=wal")
    c.execute("pragma synchronous=normal")
    c.execute("pragma busy_timeout=5000")
    return c


def setup(db: str, rows: int) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(db + suffix).unlink(missing_ok=True)
    c = connect(db)
    c.execute(
        "CREATE TABLE starpulse_events(id integer PRIMARY KEY AUTOINCREMENT, stream text NOT NULL, "
        "event_id text NOT NULL UNIQUE, fields text NOT NULL, at real NOT NULL)"
    )
    c.execute("begin")
    c.executemany(INSERT, (("machine:events", uuid.uuid4().hex, FIELDS, time.time()) for _ in range(rows)))
    c.execute("commit")
    c.close()


def append(db: str, out: mp.Queue) -> None:
    latencies = []
    for _ in range(APPENDS):
        start = time.perf_counter()
        c = connect(db)
        c.execute(INSERT, ("runs:events", uuid.uuid4().hex, FIELDS, time.time()))
        c.close()
        latencies.append(time.perf_counter() - start)
    out.put(latencies)


def reader(db: str, stop: Event, out: mp.Queue) -> None:
    c = connect(db)
    cursor = c.execute("SELECT max(id) FROM starpulse_events").fetchone()[0]
    polls = []
    while not stop.is_set():
        start = time.perf_counter()
        rows = c.execute(
            "SELECT id, stream, fields FROM starpulse_events WHERE id > ? ORDER BY id LIMIT 500", (cursor,)
        ).fetchall()
        polls.append(time.perf_counter() - start)
        if rows:
            cursor = rows[-1][0]
        time.sleep(0.25)
    out.put(polls)


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] * 1000


def main() -> None:
    db = sys.argv[1]
    for rows in (10_000, 1_000_000):
        setup(db, rows)
        out: mp.Queue = mp.Queue()
        polled: mp.Queue = mp.Queue()
        stop = mp.Event()
        rd = mp.Process(target=reader, args=(db, stop, polled))
        rd.start()
        start = time.perf_counter()
        ws = [mp.Process(target=append, args=(db, out)) for _ in range(WRITERS)]
        for w in ws:
            w.start()
        latencies = [lat for _ in ws for lat in out.get()]
        for w in ws:
            w.join()
        wall = time.perf_counter() - start
        stop.set()
        polls = polled.get()
        rd.join()
        print(
            f"rows={rows:>9}  {WRITERS} writers x {APPENDS} appends: {WRITERS * APPENDS / wall:7.0f} appends/s  "
            f"append p50={pct(latencies, 0.5):.2f}ms p99={pct(latencies, 0.99):.2f}ms | "
            f"cursor poll p50={pct(polls, 0.5):.3f}ms p99={pct(polls, 0.99):.3f}ms | "
            f"db={Path(db).stat().st_size / 1e6:.0f}MB"
        )


if __name__ == "__main__":
    main()
