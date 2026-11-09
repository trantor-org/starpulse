"""`starpulse policy show`: print the board policy that governs.

    starpulse policy show [--config starpulse.toml]

It prints one JSON document: `source` (`database` when the store's policy tables hold any policy, else `files`, the
board machine and `[board]` settings the config names) and the policy's `lanes`, `routes`, `exits`, `watches`, `rules`,
`vocabularies`, `profiles` and `tools`. The exit code is 0 once printed, 1 for a store not at the schema head and 2 for
a flag the command does not allow or a config that cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse policy", description="inspect the board policy")
    verbs = parser.add_subparsers(dest="verb", required=True)
    show = verbs.add_parser("show", help="print the loaded policy as JSON")
    show.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    # The store and the config cost over a second to import: `--help` and a flag error pay none of it.
    from sqlalchemy import create_engine  # noqa: PLC0415 - import cost, paid only by a run that shows

    from starpulse.board.adapters import policy_store  # noqa: PLC0415 - import cost, paid only by a run that shows
    from starpulse.board.model.policy import from_files  # noqa: PLC0415 - import cost, paid only by a run that shows
    from starpulse.event_log.migrate import StoreNotMigrated, require_migrated  # noqa: PLC0415 - import cost, paid only by a run that shows
    from starpulse.event_log.opening import database_url  # noqa: PLC0415 - import cost, paid only by a run that shows
    from starpulse.machine_engine.adapters.machine_loader import _read  # noqa: PLC0415 - import cost, paid only by a run that shows
    from starpulse.runtime.config import ConfigError, discover, load  # noqa: PLC0415 - import cost, paid only by a run that shows

    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    engine = create_engine(database_url(config.database_url, base))
    try:
        require_migrated(engine)
    except StoreNotMigrated as exc:
        print(f"starpulse policy: {exc}", file=sys.stderr)
        return 1
    machine = config.board.get("machine")
    source, policy = policy_store.load(
        engine, lambda: from_files(_read(base / str(machine)) if machine else {}, config.board)
    )
    print(json.dumps({"source": source, **asdict(policy)}))
    return 0
