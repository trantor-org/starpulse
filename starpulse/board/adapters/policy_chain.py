"""The operator's policy chain: the data migrations `starpulse policy revision` writes, and what they record.

The chain is a second Alembic chain beside StarPulse's, in a directory the operator names and versioned in its own table.
Each migration carries `CHANGES`, the rows it adds, removes and changes in each table by key (or, for a table whose keyed
change cannot be rebuilt in order, the whole table before and after), so the chain's head records the policy the store
should hold: the fold of every migration forward.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from alembic.util import rev_id
from sqlalchemy import URL, ColumnElement, Connection, Table, and_, column, inspect, select, table
from starpulse.board.adapters import policy_store
from starpulse.board.model.policy import Policy
from starpulse.board.model.policy_diff import KEYS, Changes, Rows, apply, changes, render, rows

__all__ = [
    "DEFAULT_VERSION_TABLE",
    "DeclaredError",
    "INI",
    "at_head",
    "declared",
    "merge",
    "recorded_rows",
    "replace",
    "scaffold",
    "write",
]

DEFAULT_VERSION_TABLE = "starpulse_operator_policy_version"
INI = "alembic.ini"

_ENV = '''\
"""Alembic's environment for the operator's policy chain: it runs on the connection a caller passes, else on `sqlalchemy.url`."""

from alembic import context
from sqlalchemy import create_engine

VERSION_TABLE = {version_table!r}


def _run(connection) -> None:
    context.configure(connection=connection, version_table=VERSION_TABLE)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    with create_engine(context.config.get_main_option("sqlalchemy.url")).begin() as connection:
        _run(connection)
'''


class DeclaredError(ValueError):
    """The operator's declared policy cannot be read."""


def replace(bind: Connection, diff: Changes, side: str) -> None:
    """Move each table `diff` names to its `side`, by key where the entry is keyed; a second run leaves the same rows."""
    for name, entry in diff.items():
        target = getattr(policy_store, name)
        if side in entry:
            bind.execute(target.delete())
            if entry[side]:
                bind.execute(target.insert(), entry[side])
            continue
        added, removed = ("add", "remove") if side == "after" else ("remove", "add")
        for row in (*entry.get(removed, []), *entry.get(added, [])):
            bind.execute(target.delete().where(_held(target, name, row)))
        for edit in entry.get("change", []):
            bind.execute(target.update().where(_held(target, name, edit["key"])).values(edit[side]))
        if entry.get(added):
            bind.execute(target.insert(), entry[added])


def _held(target: Table, name: str, row: dict[str, Any]) -> ColumnElement[bool]:
    return and_(*(target.c[column] == row[column] for column in KEYS[name]))


def declared(file: Path, attr: str) -> Policy:
    """The `Policy` the Python file `file` binds to `attr`, or that a function there returns."""
    spec = importlib.util.spec_from_file_location("starpulse_declared_policy", file)
    if spec is None or spec.loader is None or not file.is_file():
        raise DeclaredError(f"{file} is not a Python file")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, attr):
        raise DeclaredError(f"{file} defines no {attr}")
    value = getattr(module, attr)
    value = value() if callable(value) else value
    if not isinstance(value, Policy):
        raise DeclaredError(f"{file}: {attr} is not a starpulse Policy")
    return value


def scaffold(migrations: Path, version_table: str, url: URL) -> None:
    """Create the chain's directory, its Alembic environment and an `alembic.ini` for the store at `url` where they are missing."""
    (migrations / "versions").mkdir(parents=True, exist_ok=True)
    env = migrations / "env.py"
    if not env.exists():
        env.write_text(_ENV.format(version_table=version_table))
    ini = migrations / INI
    if not ini.exists():
        shown = url.render_as_string(hide_password=True).replace("%", "%%")
        ini.write_text(f"[alembic]\nscript_location = %(here)s\nsqlalchemy.url = {shown}\n")


def at_head(db: Connection, migrations: Path, version_table: str) -> bool:
    """Whether the store `db` is at the head of the chain in `migrations`; an unapplied empty chain is."""
    head = ScriptDirectory(str(migrations)).get_current_head()
    if not inspect(db).has_table(version_table):
        return head is None
    return db.execute(select(column("version_num")).select_from(table(version_table))).scalar() == head


def recorded_rows(migrations: Path) -> Rows:
    """The rows the chain's migrations leave behind, applied from the base to the head."""
    held = rows(Policy())
    for script in reversed(list(ScriptDirectory(str(migrations)).walk_revisions())):
        held = apply(held, script.module.CHANGES, "after")
    return held


def write(migrations: Path, message: str, diff: Changes) -> Path:
    """Write the next migration of the chain, applying `diff`, and return its path."""
    return _write(migrations, message, ScriptDirectory(str(migrations)).get_current_head(), diff)


def merge(migrations: Path, wanted: Policy) -> Path | None:
    """Write the migration that joins a forked chain's heads at the `wanted` policy, or None for a chain with one head.

    It sets every table a branch touched since the fork, and every table the fold leaves off `wanted`, to the `wanted`
    rows, so the merged store never depends on the order Alembic applied the branches in.
    """
    scripts = ScriptDirectory(str(migrations))
    heads = tuple(sorted(scripts.get_heads()))
    if len(heads) <= 1:
        return None
    lineages = [{script.revision for script in scripts.iterate_revisions(head, "base")} for head in heads]
    forked = set.union(*lineages) - set.intersection(*lineages)
    touched = {name for revision in forked for name in scripts.get_revision(revision).module.CHANGES}
    held, declared_rows = recorded_rows(migrations), rows(wanted)
    touched |= changes(held, declared_rows).keys()
    diff = {name: {"before": held[name], "after": declared_rows[name]} for name in held if name in touched}
    return _write(migrations, "merge policy heads", heads, diff)


def _write(migrations: Path, message: str, down_revision: str | tuple[str, ...] | None, diff: Changes) -> Path:
    revision = rev_id()
    slug = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_")[:40] or "policy"
    path = migrations / "versions" / f"{revision}_{slug}.py"
    path.write_text(render(revision, down_revision, message or "Policy revision", diff))
    return path
