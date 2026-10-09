"""The latency gate's server: `ci/preview.toml`'s synthetic workspace with a board of tasks, a lane history and a level.

`ci/preview.toml` names a board that places no task, and the level is a hub's: an IC instance parses a `[level]`
table and draws none. The gate (`bench/page_latency.py`, run nightly by trantor's whole-repo gate) needs every route and page
surface to answer something, so this serves the preview workspace with the real request handler and the built page,
and seeds what `starpulse serve` would hold after a month at a working team's scale: a Kanban of open tasks, the
lane history behind each, and the completed runs the level reads. It writes nothing outside its directory.

    uv run python -m ci.seeded_server --port 8766 --dir .tmp/gate

A server on this data is smaller than the live board: a cost that grows with the board is the nightly soak's to find.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

from starpulse._internal.server.server import StarPulseServer, assemble, request_handler
from starpulse.contracts.adapters import BoardTask
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.config.config import load
from starpulse._internal.config.history_window import HistoryWindow
from starpulse._internal.eventlog.history import HistoryStore

import starpulse

PREVIEW = Path(__file__).with_name("preview.toml")
STATIC = Path(starpulse.__file__).parent / "static"
DAY = 86400.0
#: Each open lane and how many tasks sit in it; the settled `completed` runs come on top of these.
OPEN = {"new": 4, "ready": 20, "waiting": 12, "in_progress": 18, "review": 16, "needs_attention": 4, "done": 10}
#: How many tasks have completed, which the level reads as ended runs.
COMPLETED = 80
#: The lanes a task walks to reach each lane, the order the Board machine allows.
ROUTES = {
    "new": ["new"],
    "ready": ["new", "ready"],
    "waiting": ["new", "ready", "waiting"],
    "in_progress": ["new", "ready", "in_progress"],
    "review": ["new", "ready", "in_progress", "review"],
    "needs_attention": ["new", "ready", "in_progress", "needs_attention"],
    "done": ["new", "ready", "in_progress", "review", "done"],
    "completed": ["new", "ready", "in_progress", "review", "done", "completed"],
}
#: The detours a third of the completed tasks each take: deferred and returned, or sent back from Review. The level's
#: what-if needs a state with more than one observed exit, and a send-back is what a working team's runs show.
DETOURS = {
    1: ["new", "ready", "in_progress", "needs_attention", "ready", "in_progress", "review", "done", "completed"],
    2: ["new", "ready", "in_progress", "review", "in_progress", "review", "done", "completed"],
}


def lanes() -> Iterator[str]:
    """The final lane of each seeded task, open lanes first, in the order the ids are numbered."""
    for lane, count in OPEN.items():
        yield from [lane] * count
    yield from ["completed"] * COMPLETED


def steps(final: str, index: int, now: float) -> list[tuple[str, float]]:
    """Each lane the task `index` passed through on its way to `final` and when it entered it, oldest first.

    Tasks are numbered oldest first, spread over a month, and every step is a few hours after the last, so a task
    still in a lane has waited there a while and the level has aging to read.
    """
    route = DETOURS.get(index % 3, ROUTES[final]) if final == "completed" else ROUTES[final]
    start = now - 30 * DAY + index * (29 * DAY / sum(OPEN.values(), COMPLETED))
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


def seed(feed: BoardFeed, store: HistoryStore, now: float) -> dict[str, dict]:
    """Place every seeded task on the feed with its lane history in the store; the records the modal reads, by id.

    The whole history goes in one transaction and the feed records nothing: a commit per lane change takes minutes on a
    loaded runner. The gate never moves a task, so the feed needs no recorder.
    """
    paths = {f"DEMO-{index}": (final, steps(final, index, now)) for index, final in enumerate(lanes())}
    with store.engine.begin() as db:
        for task_id, (_, path) in paths.items():
            for lane, at in path:
                store._fold_lane(db, f"{task_id}@{lane}@{at}", task_id, lane, at)
    records: dict[str, dict] = {}
    for index, (task_id, (final, path)) in enumerate(paths.items()):
        entered = path[-1][1]
        settled = final == "completed"
        feed.put(
            BoardTask(
                id=task_id,
                title=f"Demo task {index}",
                team="demo",
                lane="done" if settled else final,
                dependencies=(f"DEMO-{index - 1}",) if final == "waiting" else (),
                settled="completed" if settled else None,
                created_at=path[0][1],
                settled_at=entered if settled else None,
                observed_at=entered,
            )
        )
        records[task_id] = record(index, final)
    return records


def serve(port: int, directory: Path, *, now: float | None = None) -> ThreadingHTTPServer:
    """The seeded server, bound to `port` on this machine; the caller runs `serve_forever`."""
    directory.mkdir(parents=True, exist_ok=True)
    config = load(PREVIEW)
    _, feed = assemble(config, PREVIEW.parent, None, [])
    store = HistoryStore(f"sqlite:///{directory / 'history.sqlite'}", feed.machines)
    records = seed(feed, store, time.time() if now is None else now)
    window = HistoryWindow(feed, 24 * 7, directory / "starpulse-settings.json")
    handler = request_handler(
        feed, STATIC, {}, [], store, window, read=lambda task: records.get(task), level=config.level
    )
    return StarPulseServer(("127.0.0.1", port), handler)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover — process boundary
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--dir", type=Path, required=True, help="where the history database and settings are written")
    args = parser.parse_args(argv)
    server = serve(args.port, args.dir)
    print(f"seeded StarPulse on :{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
