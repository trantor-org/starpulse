"""`starpulse refold --config FILE`: replace each read-model table family folded under another stamp than this code's.

The Board writer starts one as a child for each stale family, so the families replay in parallel and each holds the write lock only for its own swap; so a deploy's `starpulse migrate` replays nothing. The
replay runs in this process's memory while the old rows keep serving; one write transaction then swaps the new rows in.
It prints one JSON line: `refolded`, the families replaced. The exit code is 2 for a config that cannot be read.
"""

import argparse
import json
import logging
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.contracts.adapters import TaskKeys
    from starpulse.event_log.readmodel.projector import Projector
    from starpulse.event_log.wake import StopEvent
lazy from starpulse.event_log.event_log import EventLog, store_engine
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.event_log.readmodel.projector import FAMILY, MACHINE_FAMILY, Projector
lazy from starpulse.event_log.store import EventStore
lazy from starpulse.runtime.assembly import declared
lazy from starpulse.runtime.config import ConfigError, discover, load, rehearsing

__all__ = ["main", "refold", "spawn"]

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Refold the store the config names; 0 once no family is stale."""
    parser = argparse.ArgumentParser(prog="starpulse refold", description="replace the stale read-model tables")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--family", action="append", choices=(FAMILY, MACHINE_FAMILY), help="refold only this family; repeatable")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    try:
        board, machines, *_ = declared(config, base)
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    families = refold(database_url(config.database_url, base), machines, keys=board.keys, only=args.family)
    print(json.dumps({"refolded": families}))
    return 0


def refold(
    url: str, machines: Mapping[str, dict], *, keys: TaskKeys | None = None, only: Sequence[str] | None = None
) -> list[str]:
    """Replace each family (of `only`, when given) of the store at `url` folded under another stamp; the families replaced."""
    engine = store_engine(url)
    try:
        log = EventLog(url, engine=engine)
        return Projector(engine, EventStore(engine), log=log, drawn=machines, keys=keys).refold(only)
    finally:
        engine.dispose()


def spawn(projector: Projector, path: Path | None, stop: StopEvent) -> list[subprocess.Popen]:
    """Start `starpulse refold` as one child per stale family of `projector`, in parallel, each ended when `stop` is set.
    A rehearsal refolds nothing: it serves the copy it was given."""
    if rehearsing():
        return []
    return [_child(family, path, stop) for family in projector.stale()]


def _child(family: str, path: Path | None, stop: StopEvent) -> subprocess.Popen:
    command = [sys.executable, "-m", "starpulse", "refold", "--family", family, *(["--config", str(path)] if path else [])]
    child = subprocess.Popen(command)  # noqa: S603 - this interpreter and our own module
    stop.listen(child.terminate)

    def report() -> None:
        if code := child.wait():
            logger.error("StarPulse: the %s refold ended with %s; it runs again at the next start", family, code)

    threading.Thread(target=report, name=f"refold-{family}", daemon=True).start()
    return child
