"""Flow reads benchmark: flow health and the level over a store of 10 thousand, 1 million and 10 million lane changes.

The Board's lane changes are recorded at a fixed rate (about 125 a day, 22 tasks arriving a day), so a bigger store is
a longer history, not a busier week. The store summarises them as `HistoryStore.rebuild_summaries` does at start-up,
then `health_response`, `level_response` and `trajectories_response` are each asked for the default week 60 times and
their p95 is printed in wall and in CPU time. A read that scanned every lane change would grow with the store; one that
reads the summaries costs what the week, the trailing 12 weeks and the tasks in flight cost, whatever the history. The
run ends by checking that the CPU p95 at every size after the first is within 2x of the first (CPU time, because a
shared host stretches the wall time).

Run this file from the repository root with ``uv run python bench/flow_reads.py <dir> [sizes...]``. The stores are
SQLite files in ``<dir>`` (about 300 MB per million events), replaced on each run, or read as they are with
``--reuse``; sizes default to 10000, 1000000 and 10000000. ``--scan N`` also times the whole-table reads the summaries
replaced, on the stores up to N events, in 3 reads each.
"""

import argparse
import heapq
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import event
from starpulse.domain.level import Level, Orbit, Terminal
from starpulse.server import health_response, level_response, trajectories_response
from starpulse.store.history import HistoryStore
from starpulse.upstream_backlog import board_machine

LANES = ("To Do", "Ready", "In Progress", "Review", "Done")
MACHINES = {"board": board_machine(LANES)}
LEVEL = Level(
    "board",
    "done",
    (Terminal("done", "goal"),),
    gates=("review",),
    orbit=Orbit("working", ("in_progress", "review")),
)
START = 1_700_000_000.0
HOUR = 3600.0
#: Mean hours between task arrivals, and the mean hours a task rests in each lane before its next change.
ARRIVAL_H = 1.09
DWELL_H = {"To Do": 12.0, "Ready": 24.0, "In Progress": 24.0, "Review": 8.0}
#: The share of tasks whose review sends them back to work once.
REWORK = 0.2
REPEATS = 60
CHUNK = 50_000
INSERT = (
    "INSERT INTO starpulse_lane_changes (event_id, task, old_status, new_status, observed_at) VALUES (?, ?, ?, ?, ?)"
)


def lane_changes(events: int, seed: int = 7):
    """`events` lane changes `(event_id, task, old, new, at)` in the order they happened, two sources reporting."""
    rng = random.Random(seed)
    arrivals, live, made, task = START, [], 0, 0
    while made < events:
        # the next lane change is the earliest of the next arrival and the tasks in flight
        if not live or arrivals <= live[0][0]:
            task += 1
            at, arrivals = arrivals, arrivals + rng.expovariate(1 / ARRIVAL_H) * HOUR
            path = [
                "To Do",
                "Ready",
                "In Progress",
                "Review",
                *(["In Progress", "Review"] if rng.random() < REWORK else []),
                "Done",
            ]
            source = "a" if task % 2 else "b"
            heapq.heappush(live, (at, task, source, path, 0))
            continue
        at, task_id, source, path, step = heapq.heappop(live)
        made += 1
        yield f"{source}/{made}", f"T-{task_id}", path[step - 1] if step else None, path[step], at
        if step + 1 < len(path):
            wait = rng.expovariate(1 / DWELL_H[path[step]]) * HOUR
            heapq.heappush(live, (at + wait, task_id, source, path, step + 1))


def fill(store: HistoryStore, events: int) -> float:
    """Write `events` raw lane changes and return the time of the last."""
    last, rows = START, []
    with store.engine.connect() as db:
        db.exec_driver_sql("PRAGMA synchronous = OFF")
        for row in lane_changes(events):
            rows.append(row)
            last = row[4]
            if len(rows) == CHUNK:
                db.exec_driver_sql(INSERT, rows)
                rows.clear()
        if rows:
            db.exec_driver_sql(INSERT, rows)
        db.commit()
    return last


class RowScan:
    """A history of the lane changes and nothing else: the reads fold every one, as before the summaries."""

    def __init__(self, store: HistoryStore) -> None:
        self.lane_path, self.machine_path = store.lane_path, store.machine_path
        self.lane_rows, self.gaps, self.level_runs = store.lane_rows, store.gaps, store.level_runs


class Timing(NamedTuple):
    wall: float
    cpu: float


def p95(read: Callable[[], object], repeats: int) -> Timing:
    """The 95th-percentile wall and CPU milliseconds of `repeats` reads, after one that warms the page cache."""
    read()
    wall, cpu = [], []
    for _ in range(repeats):
        start, busy = time.perf_counter(), time.thread_time()
        read()
        wall.append((time.perf_counter() - start) * 1000)
        cpu.append((time.thread_time() - busy) * 1000)
    rank = min(repeats - 1, int(repeats * 0.95))
    return Timing(sorted(wall)[rank], sorted(cpu)[rank])


def reads(history, now: float) -> dict[str, Callable[[], object]]:
    def ask(answer):
        def read():
            body, status = answer(history)
            assert status == 200, body
            return body

        return read

    return {
        "health": ask(lambda h: health_response(h, {}, MACHINES, now)),
        "level": ask(lambda h: level_response(h, {}, LEVEL, MACHINES, now)),
        "trajectories": ask(lambda h: trajectories_response(h, {}, LEVEL, MACHINES, now)),
    }


def statements(store: HistoryStore, read: Callable[[], object]) -> int:
    """How many SQL statements one read sends."""
    count = [0]

    def seen(*_args) -> None:
        count[0] += 1

    event.listen(store.engine, "before_cursor_execute", seen)
    read()
    event.remove(store.engine, "before_cursor_execute", seen)
    return count[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("sizes", type=int, nargs="*", default=[10_000, 1_000_000, 10_000_000])
    parser.add_argument(
        "--scan", type=int, default=0, metavar="N", help="also time the whole-table reads up to N events"
    )
    parser.add_argument(
        "--reuse", action="store_true", help="read the stores a run left in the directory, not new ones"
    )
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    results: dict[int, dict[str, Timing]] = {}
    for events in args.sizes:
        path = args.directory / f"flow-reads-{events}.sqlite"
        loaded = summarised = 0.0
        if args.reuse and path.exists():
            store = HistoryStore(f"sqlite:///{path}", MACHINES)
            with store.engine.connect() as db:
                now = db.exec_driver_sql("SELECT max(observed_at) FROM starpulse_lane_changes").scalar() + HOUR
        else:
            path.unlink(missing_ok=True)
            store = HistoryStore(f"sqlite:///{path}", MACHINES)
            start = time.perf_counter()
            now = fill(store, events) + HOUR
            loaded = time.perf_counter() - start
            start = time.perf_counter()
            store.rebuild_summaries()
            summarised = time.perf_counter() - start
        timed = {name: p95(read, REPEATS) for name, read in reads(store, now).items()}
        results[events] = timed
        print(
            f"events={events:>10}  load={loaded:6.1f}s summarise={summarised:6.1f}s  db={path.stat().st_size / 1e6:6.0f}MB  "
            + "  ".join(
                f"{name} p95={t.wall:7.1f}ms wall {t.cpu:7.1f}ms cpu ({statements(store, reads(store, now)[name])} statements)"
                for name, t in timed.items()
            ),
            flush=True,
        )
        if events <= args.scan:
            scanned = {
                name: p95(read, 3) for name, read in reads(RowScan(store), now).items() if name != "trajectories"
            }
            print(
                f"{'':>17}whole-table scan: "
                + "  ".join(f"{name} p95={t.wall:9.1f}ms wall {t.cpu:9.1f}ms cpu" for name, t in scanned.items()),
                flush=True,
            )
        store.engine.dispose()
    first = results[args.sizes[0]]
    failed = False
    for events, timed in results.items():
        verdict = {name: t.cpu / first[name].cpu for name, t in timed.items()}
        failed |= any(ratio > 2 for ratio in verdict.values())
        print(
            f"events={events:>10}  CPU p95 against the first size: "
            + "  ".join(f"{n} x{r:.2f}" for n, r in verdict.items())
        )
    print("within 2x at every size" if not failed else "OVER 2x at some size")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
