"""`starpulse policy`: print the board policy that governs, or write the migration that brings the store to the declared one.

    starpulse policy show [--config starpulse.toml]
    starpulse policy revision [--config starpulse.toml] [-m MESSAGE]

`show` prints one JSON document: `source` (`database` when the store's policy tables hold any policy, else `files`, the
board machine and `[board]` settings the config names) and the policy's `lanes`, `routes`, `exits`, `watches`, `rules`,
`vocabularies`, `profiles` and `tools`. The exit code is 0 once printed, 1 for a store not at the schema head and 2 for
a flag the command does not allow or a config that cannot be read.

`revision` diffs the operator's declared `Policy` (`[board.policy] declared`, a Python file and optionally `:ATTR`, default
`POLICY`) against the store and writes a data migration into the operator's Alembic chain (`migrations`, its directory,
versioned in `version_table`). It exits 0 after printing the migration's path, or when the store already matches the
declared policy and writes nothing. It exits 1 for a store not at the head of either chain, 2 for a usage or declaration
error, and 3 when the store holds policy the chain never wrote (a hand SQL edit): the drift is printed to stderr and no
migration is written, so the edit is never overwritten.
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
    revision = verbs.add_parser("revision", help="write the migration that brings the store to the declared policy")
    revision.add_argument("-m", "--message", default="", help="the migration's title")
    for verb in (show, revision):
        verb.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    # The store and the config cost over a second to import: `--help` and a flag error pay none of it.
    from sqlalchemy import create_engine  # noqa: PLC0415 - import cost, paid only by a run that shows

    from starpulse.event_log.migrate import StoreNotMigrated, require_migrated  # noqa: PLC0415 - import cost, paid only by a run that shows
    from starpulse.event_log.opening import database_url  # noqa: PLC0415 - import cost, paid only by a run that shows
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
    if args.verb == "revision":
        return _revision(parser, engine, config.board, base, args.message)
    return _show(engine, config.board, base)


def _show(engine, board, base: Path) -> int:  # noqa: ANN001 - the engine and board are typed where they are imported
    from starpulse.board.adapters.lane_policy import load_policy  # noqa: PLC0415 - import cost, paid only by a run that shows

    source, policy = load_policy(engine, board, base)
    print(json.dumps({"source": source, **asdict(policy)}))
    return 0


def _revision(parser: argparse.ArgumentParser, engine, board, base: Path, message: str) -> int:  # noqa: ANN001
    from starpulse.board.adapters import policy_chain, policy_store  # noqa: PLC0415 - import cost, paid only by a run that revises
    from starpulse.board.model.policy_diff import changes, drift_report, rows  # noqa: PLC0415 - import cost, paid only by a run that revises

    settings = board.get("policy")
    if not isinstance(settings, dict) or not {"declared", "migrations"} <= settings.keys():
        parser.error("[board.policy] needs `declared` (a Python file, optionally `:ATTR`) and `migrations` (the chain's directory)")
    file, _, attr = str(settings["declared"]).partition(":")
    migrations = base / str(settings["migrations"])
    version_table = str(settings.get("version_table", policy_chain.DEFAULT_VERSION_TABLE))
    try:
        wanted = policy_chain.declared(base / file, attr or "POLICY")
    except (policy_chain.DeclaredError, OSError, SyntaxError) as exc:
        parser.error(str(exc))
    policy_chain.scaffold(migrations, version_table, engine.url)
    with engine.connect() as db:
        if not policy_chain.at_head(db, migrations, version_table):
            ini = migrations / policy_chain.INI
            print(f"starpulse policy: the store is behind the operator chain: run `alembic -c {ini} upgrade head`", file=sys.stderr)
            return 1
        held = policy_store.stored(db)
    expected = policy_chain.recorded_rows(migrations)
    drift = drift_report(expected, rows(held))
    if drift:
        print("starpulse policy: the store differs from what the operator chain wrote; no revision written", file=sys.stderr)
        print("\n".join(drift), file=sys.stderr)
        return 3
    diff = changes(expected, rows(wanted))
    if not diff:
        print("starpulse policy: the store matches the declared policy; no revision written")
        return 0
    print(policy_chain.write(migrations, message, diff))
    return 0
