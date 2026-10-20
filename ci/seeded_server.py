"""The latency gate's server: `ci/preview.toml`'s synthetic workspace with a board of tasks, a lane history and a level.

`ci/preview.toml` names a board that places no task, and an IC instance parses a `[level]` table and draws none. The
gate (`bench/page_latency.py`, run nightly by trantor's whole-repo gate) needs every route and page surface to answer
something, so this serves the preview workspace with the real request handler and the built page,
and seeds what `starpulse serve` would hold after a month at a working team's scale: a Kanban of open tasks, the
lane history behind each, the finished runs the level reads, the milestone and doc files of a native board, and an
autopilot with one capacity reading. It writes nothing outside its directory.

    uv run python -m ci.seeded_server --port 8766 --dir .tmp/gate

`--replay-rate N` also moves a seeded task between In Progress and Review N times a second, as `bench/soak.py` runs it:
every move is an event on each open stream, which a static board never sends. `--port 0` takes a free port.

A server on this data is smaller than the live board: a cost that grows with the board is the nightly soak's to find.
"""

from __future__ import annotations

import argparse
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

from sqlalchemy import Engine, event
from starpulse._internal.autopilot.runtime import Runtime
from starpulse._internal.autopilot.runtime import build as build_autopilot
from starpulse._internal.board import native
from starpulse._internal.board.seam import Board, Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.eventlog.lane_import import Change
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.history_window import HistoryWindow
from starpulse._internal.server.asgi_app import page_app
from starpulse._internal.server.assembly import assemble
from starpulse._internal.server.page_server import PageServer
from starpulse._internal.server.services import Services
from starpulse.contracts.adapters import BoardTask

import starpulse

PREVIEW = Path(__file__).with_name("preview.toml")
STATIC = Path(starpulse.__file__).parent / "static"
DAY = 86400.0
#: Each lane short of Done and how many tasks sit in it; the finished runs come on top of these.
OPEN = {"new": 4, "ready": 20, "waiting": 12, "in_progress": 18, "review": 16, "needs_attention": 4}
#: How many tasks are in Done, which the level reads as ended runs.
DONE = 90
#: How many open milestones and docs the native board holds, about half of what the live board keeps open: a doc read
#: parses every doc file (about 0.4 ms each), so this leaves the route a margin under the budget on a loaded runner.
MILESTONES = 16
DOCS = 24
#: The host reading the autopilot's sampler takes once, so the capacity strip has dimensions to draw.
HOST = {"cpu": 0.25, "memory": 0.4}
#: The lanes a task walks to reach each lane, the order the Board machine allows.
ROUTES = {
    "new": ["new"],
    "ready": ["new", "ready"],
    "waiting": ["new", "ready", "waiting"],
    "in_progress": ["new", "ready", "in_progress"],
    "review": ["new", "ready", "in_progress", "review"],
    "needs_attention": ["new", "ready", "in_progress", "needs_attention"],
    "done": ["new", "ready", "in_progress", "review", "done"],
}
#: The detours a third of the Done tasks each take: deferred and returned, or sent back from Review. The level's
#: what-if needs a state with more than one observed exit, and a send-back is what a working team's runs show.
DETOURS = {
    1: ["new", "ready", "in_progress", "needs_attention", "ready", "in_progress", "review", "done"],
    2: ["new", "ready", "in_progress", "review", "in_progress", "review", "done"],
}


#: The two lanes the replay moves tasks between; the Board machine allows the move to Review and the send-back.
FLIP = {"in_progress": "review", "review": "in_progress"}


def lanes() -> Iterator[str]:
    """The final lane of each seeded task, open lanes first, in the order the ids are numbered."""
    for lane, count in OPEN.items():
        yield from [lane] * count
    yield from ["done"] * DONE


def steps(final: str, index: int, now: float) -> list[tuple[str, float]]:
    """Each lane the task `index` passed through on its way to `final` and when it entered it, oldest first.

    Tasks are numbered oldest first, spread over a month, and every step is a few hours after the last, so a task
    still in a lane has waited there a while and the level has aging to read.
    """
    route = DETOURS.get(index % 3, ROUTES[final]) if final == "done" else ROUTES[final]
    start = now - 30 * DAY + index * (29 * DAY / sum(OPEN.values(), DONE))
    return [(lane, start + n * 5 * 3600.0) for n, lane in enumerate(route)]


def record(index: int, final: str) -> dict:
    """The task's board record, every field the modal draws."""
    return {
        "title": f"Demo task {index}",
        "type": "task",
        "status": final.replace("_", " ").title(),
        "profile": "agent",
        "priority": "medium",
        "labels": ["demo", f"size-{1 + index % 5}"],
        "milestone": f"m-{1 + index % 4}",
        "dependencies": [f"DEMO-{index - 1}"] if index else [],
        "references": [],
        "documentation": [],
        "modifiedFiles": [],
        "description": f"A synthetic task, number {index}, for the latency gate.\n\n" + "A line of detail. " * 40,
        "start_criteria": [],
        "plan": "1. Read it.\n2. Change it.\n3. Prove it.",
        "notes": "",
        "finalSummary": "",
        "comments": [],
        "acceptanceCriteria": [{"text": f"Criterion {n}", "checked": n % 2 == 0} for n in range(1, 6)],
        "definitionOfDone": [{"text": "Gates pass", "checked": False}],
    }


def seed(feed: BoardFeed, store: HistoryStore, now: float) -> tuple[dict[str, dict], list[BoardTask]]:
    """Place every seeded task on the feed with its lane history in the store; the records the modal reads, by id, and
    the tasks as placed.

    The whole history goes in as one import and the feed records nothing: a commit per lane change takes minutes on a
    loaded runner, and folding each change as it lands costs several statements apiece where the import writes the
    rows and folds the summaries once. The gate never moves a task, so the feed needs no recorder.
    """
    paths = {f"DEMO-{index}": (final, steps(final, index, now)) for index, final in enumerate(lanes())}
    store.import_lanes(
        Change(f"{task_id}@{lane}@{at}", task_id, lane, at) for task_id, (_, path) in paths.items() for lane, at in path
    )
    records: dict[str, dict] = {}
    placed: list[BoardTask] = []
    for index, (task_id, (final, path)) in enumerate(paths.items()):
        task = BoardTask(
            id=task_id,
            title=f"Demo task {index}",
            team="demo",
            lane=final,
            dependencies=(f"DEMO-{index - 1}",) if final == "waiting" else (),
            created_at=path[0][1],
            observed_at=path[-1][1],
        )
        feed.put(task)
        placed.append(task)
        records[task_id] = record(index, final)
    return records, placed


def native_board(directory: Path) -> Board:
    """A native board under `directory` holding `MILESTONES` milestones and `DOCS` docs, filed through its own writers
    so the files are the ones a real board keeps and the routes read them from disk."""
    board = native.board({}, directory)
    assert board.create_milestone is not None and board.create_doc is not None
    filed = [
        board.create_milestone(f"Demo milestone {n}", {"outcome": "A synthetic outcome.", "specs": [], "adrs": []})
        for n in range(1, MILESTONES + 1)
    ] + [
        board.create_doc(
            f"Demo doc {n}",
            {"type": ("specification", "guide", "readme", "other")[n % 4], "body": "A line of detail. " * 40},
        )
        for n in range(1, DOCS + 1)
    ]
    if refused := next((written for written in filed if not written.ok), None):
        raise RuntimeError(f"the seeded board refused a record: {refused.output}")
    return board


def autopilot(directory: Path, log: EventLog, feed: BoardFeed, policy: Autopilot) -> Runtime:
    """The autopilot `GET /api/autopilot` reads, with its loop built over a starter that starts nothing, one capacity
    sample taken and no thread running: the route reads the last sample and the loop's next pick, as a served one does."""
    runtime = build_autopilot(
        policy,
        directory,
        log,
        feed,
        lambda: HOST,
        start=lambda task, **_: "",
        settle=lambda task, reason: Written(True, ""),
        lane=policy.eligible_lane(next(s["id"] for s in feed.machines["board"]["states"] if s.get("initial"))),
    )
    runtime.sampler.sample()
    return runtime


def _without_sync(connection: object, _record: object) -> None:
    """No sync per commit: the seed writes a few thousand rows to a store that is gone with its directory."""
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA synchronous=OFF")


def build(port: int, directory: Path, *, now: float | None = None) -> tuple[PageServer, BoardFeed, list[BoardTask]]:
    """The seeded server bound to `port` (0: any free one), the feed it draws and the tasks seeded on it."""
    directory.mkdir(parents=True, exist_ok=True)
    if not event.contains(Engine, "connect", _without_sync):
        event.listen(Engine, "connect", _without_sync)
    config = load(PREVIEW)
    _, feed = assemble(config, PREVIEW.parent, None, [])
    log = EventLog(f"sqlite:///{directory / 'history.sqlite'}")
    store = HistoryStore(log.url, feed.machines)
    records, tasks = seed(feed, store, time.time() if now is None else now)
    window = HistoryWindow(feed, 24 * 7, log, directory / "starpulse-settings.json")
    # The preview reads its seeded task records and the native milestones and docs, and refuses every task write.
    board = replace(
        native_board(directory),
        writer=None,
        assign=None,
        edit=None,
        archive=None,
        restore=None,
        complete=None,
        create=None,
        read=lambda task: records.get(task),
    )
    services = Services(level=config.level, autopilot=autopilot(directory, log, feed, config.autopilot))
    app = page_app(feed, STATIC, store, window, board, services)
    return PageServer(app, ("127.0.0.1", port)), feed, tasks


def serve(port: int, directory: Path, *, now: float | None = None) -> PageServer:
    """The seeded server, bound to `port` on this machine; the caller starts it."""
    return build(port, directory, now=now)[0]


def replay(
    feed: BoardFeed,
    tasks: list[BoardTask],
    rate: float,
    wait: Callable[[float], bool],
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Move the seeded tasks that are in progress or in review to the other lane, `rate` moves a second, and return
    how many were made once `wait` (`threading.Event.wait`, which returns True when set) says the run is over.

    Every move is a `task` event on each open stream, as a working team's moves are, and the first pass sends each
    task one way and the next sends it back. The pace is held against the clock, so a slow move is made up for.
    """
    held = [task for task in tasks if task.lane in FLIP]
    interval = 1.0 / rate
    due, sent = clock(), 0
    while True:
        task = held[sent % len(held)]
        held[sent % len(held)] = task = task.model_copy(update={"lane": FLIP[task.lane], "observed_at": time.time()})
        feed.put(task)
        sent += 1
        due += interval
        if wait(max(0.0, due - clock())):
            return sent


def main(argv: list[str] | None = None) -> None:  # pragma: no cover — process boundary
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True, help="0 takes any free port, which the first line prints")
    parser.add_argument("--dir", type=Path, required=True, help="where the history database and settings are written")
    parser.add_argument(
        "--replay-rate",
        type=float,
        help="moves a second of seeded tasks between In Progress and Review, sent to every stream until the server stops",
    )
    args = parser.parse_args(argv)
    server, feed, tasks = build(args.port, args.dir)
    print(f"seeded StarPulse on :{server.server_port}", flush=True)
    stop, sent = threading.Event(), []
    feeder = threading.Thread(target=lambda: sent.append(replay(feed, tasks, args.replay_rate, stop.wait)), daemon=True)
    if args.replay_rate:
        feeder.start()
    try:
        server.run()  # SIGTERM and Ctrl-C stop it
    finally:
        stop.set()
        if args.replay_rate:
            feeder.join()
            print(f"replayed {sent[0]} events", flush=True)


if __name__ == "__main__":
    main()
