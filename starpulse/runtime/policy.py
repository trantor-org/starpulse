"""`starpulse policy`: print the board policy that governs, or write the migration that brings the store to the declared one.

    starpulse policy show [--config starpulse.toml]
    starpulse policy revision [--config starpulse.toml] [-m MESSAGE]
    starpulse policy merge [--config starpulse.toml]
    starpulse policy export [--out FILE] [--config starpulse.toml]
    starpulse policy import FILE [--config starpulse.toml]

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

`merge` joins a chain forked into two or more heads with one migration that sets every table a branch touched to the
declared rows, so the store needs no connection and the result never depends on the order the branches apply. It prints
the migration's path, or that the chain has one head, and exits 0; 2 is a usage or declaration error.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

lazy from sqlalchemy import create_engine

lazy from starpulse.board.adapters import policy_chain
lazy from starpulse.board.adapters.lane_policy import load_policy
lazy from starpulse.board.model.policy_diff import changes, drift_report, rows
lazy from starpulse.event_log.migrate import StoreNotMigrated, require_migrated
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse policy", description="inspect the board policy")
    verbs = parser.add_subparsers(dest="verb", required=True)
    show = verbs.add_parser("show", help="print the loaded policy as JSON")
    revision = verbs.add_parser("revision", help="write the migration that brings the store to the declared policy")
    revision.add_argument("-m", "--message", default="", help="the migration's title")
    merge = verbs.add_parser("merge", help="join a forked operator chain's heads at the declared policy")
    export = verbs.add_parser("export", help="write the governing policy as a JSON document")
    export.add_argument("--out", type=Path, help="the file to write (default stdout)")
    importer = verbs.add_parser("import", help="make a JSON policy document the store's active policy")
    importer.add_argument("file", type=Path, help="a document `export` wrote")
    for verb in (show, revision, merge, export, importer):
        verb.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)

    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    if args.verb == "merge":
        return _merge(parser, config.board, base)
    engine = create_engine(database_url(config.database_url, base))
    try:
        require_migrated(engine)
    except StoreNotMigrated as exc:
        print(f"starpulse policy: {exc}", file=sys.stderr)
        return 1
    if args.verb == "revision":
        return _revision(parser, engine, config.board, base, args.message)
    if args.verb == "export":
        return _export(engine, config.board, base, args.out)
    if args.verb == "import":
        return _import(parser, engine, args.file)
    return _show(engine, config.board, base)


def _show(engine, board, base: Path) -> int:  # noqa: ANN001 - the engine and board are typed where they are imported

    source, policy = load_policy(engine, board, base)
    print(json.dumps({"source": source, **asdict(policy)}))
    return 0


def _export(engine, board, base: Path, out: Path | None) -> int:  # noqa: ANN001 - the engine and board are typed where they are imported
    from starpulse.board.adapters.lane_policy import load_policy  # noqa: PLC0415 - import cost, paid only by a run that exports
    from starpulse.board.model.policy_diff import rows  # noqa: PLC0415 - import cost, paid only by a run that exports

    text = json.dumps(rows(load_policy(engine, board, base)[1]), indent=2)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n")
    return 0


def _import(parser: argparse.ArgumentParser, engine, file: Path) -> int:  # noqa: ANN001
    from starpulse.board.adapters import policy_store  # noqa: PLC0415 - import cost, paid only by a run that imports
    from starpulse.board.model.policy import Policy  # noqa: PLC0415 - import cost, paid only by a run that imports
    from starpulse.board.model.policy_diff import policy_of, rows  # noqa: PLC0415 - import cost, paid only by a run that imports

    try:
        held = json.loads(file.read_text())
        missing = [table for table in rows(Policy()) if table not in held]
        if missing:
            parser.error(f"{file}: not a policy document: missing tables {', '.join(missing)}")
        wanted = policy_of(held)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.error(f"{file}: not a policy document: {exc}")
    with engine.begin() as db:
        print(policy_store.write(db, wanted))
    return 0


def _chain(parser: argparse.ArgumentParser, board, base: Path):  # noqa: ANN001, ANN202 - the board and Policy are typed where they are imported

    settings = board.get("policy")
    if not isinstance(settings, dict) or not {"declared", "migrations"} <= settings.keys():
        parser.error(
            "[board.policy] needs `declared` (a Python file, optionally `:ATTR`) and `migrations` (the chain's directory)"
        )
    file, _, attr = str(settings["declared"]).partition(":")
    try:
        wanted = policy_chain.declared(base / file, attr or "POLICY")
    except (policy_chain.DeclaredError, OSError, SyntaxError) as exc:
        parser.error(str(exc))
    return (
        base / str(settings["migrations"]),
        str(settings.get("version_table", policy_chain.DEFAULT_VERSION_TABLE)),
        wanted,
    )


def _merge(parser: argparse.ArgumentParser, board, base: Path) -> int:  # noqa: ANN001

    migrations, _, wanted = _chain(parser, board, base)
    written = policy_chain.merge(migrations, wanted)
    print(written or "starpulse policy: the operator chain has one head; no merge written")
    return 0


def _revision(parser: argparse.ArgumentParser, engine, board, base: Path, message: str) -> int:  # noqa: ANN001
    from starpulse.board.adapters import policy_chain, policy_store  # noqa: PLC0415 - import cost, paid only by a run that revises

    migrations, version_table, wanted = _chain(parser, board, base)
    policy_chain.scaffold(migrations, version_table, engine.url)
    with engine.connect() as db:
        if not policy_chain.at_head(db, migrations, version_table):
            ini = migrations / policy_chain.INI
            print(
                f"starpulse policy: the store is behind the operator chain: run `alembic -c {ini} upgrade head`",
                file=sys.stderr,
            )
            return 1
        held = policy_store.stored(db)
    expected = policy_chain.recorded_rows(migrations)
    drift = drift_report(expected, rows(held))
    if drift:
        print(
            "starpulse policy: the store differs from what the operator chain wrote; no revision written",
            file=sys.stderr,
        )
        print("\n".join(drift), file=sys.stderr)
        return 3
    diff = changes(expected, rows(wanted))
    if not diff:
        print("starpulse policy: the store matches the declared policy; no revision written")
        return 0
    print(policy_chain.write(migrations, message, diff))
    return 0
