"""The rows a policy is stored as, and the difference between two policies as the data migration that moves one to the other."""

from __future__ import annotations

import json
import pprint
from dataclasses import asdict
from typing import Any

from starpulse.board.model.policy import Exit, Lane, LaneTool, Policy, PolicyRule, Profile, Route, Vocabulary, Watch

__all__ = ["KEYS", "Changes", "Rows", "apply", "changes", "drift_report", "render", "rows"]

Rows = dict[str, list[dict[str, Any]]]
#: A changed table is either keyed (`add`, `remove` and `change` entries) or whole (`before` and `after` rows, the older form).
Changes = dict[str, dict[str, list[dict[str, Any]]]]

TABLE_PREFIX = "starpulse_policy_"
_ROW: dict[str, type] = {
    "lanes": Lane,
    "routes": Route,
    "exits": Exit,
    "watches": Watch,
    "rules": PolicyRule,
    "vocabularies": Vocabulary,
    "profiles": Profile,
    "tools": LaneTool,
}
#: The columns that identify a row of each table in a keyed change; `rules` are identified by their position.
KEYS: dict[str, tuple[str, ...]] = {
    "lanes": ("name",),
    "routes": ("event", "source", "target"),
    "exits": ("event", "actor", "trigger"),
    "watches": ("lane", "fact"),
    "rules": ("position",),
    "vocabularies": ("name", "value"),
    "profiles": ("kind", "size"),
    "tools": ("lane", "tool"),
}
#: The columns a table's rows sort by; `routes` and `exits` have none, as their declared order is the store's insert order.
_ORDER: dict[str, tuple[str, ...]] = {
    "lanes": ("position",),
    "watches": ("lane", "position"),
    "rules": ("position",),
    "vocabularies": ("name", "position"),
    "profiles": ("kind", "size"),
    "tools": ("lane", "tool"),
}


def rows(policy: Policy) -> Rows:
    """The table rows `policy` is stored as, JSON-plain and in the order the store reads them."""
    held = json.loads(json.dumps(asdict(policy)))
    return {table: _sorted(table, held[table]) for table in _ROW}


def changes(before: Rows, after: Rows) -> Changes:
    """Each table whose rows differ: its rows added, removed and changed by key, else both sides whole."""
    diff: Changes = {}
    for table in _ROW:
        if before[table] != after[table]:
            diff[table] = _keyed(table, before[table], after[table]) or {"before": before[table], "after": after[table]}
    return diff


def apply(held: Rows, diff: Changes, side: str) -> Rows:
    """`held` with each changed table moved to the `side` (`before` or `after`) of `diff`."""
    return {table: _moved(table, held[table], diff[table], side) if table in diff else held[table] for table in _ROW}


def render(revision: str, down_revision: str | tuple[str, ...] | None, message: str, diff: Changes) -> str:
    """The text of the migration `revision` that applies `diff`; it moves each changed table by its keyed rows."""
    title = " ".join(message.replace("\\", "\\\\").replace('"', "'").split())
    return (
        f'"""{title}\n\nRevision ID: {revision}\nRevises: {down_revision}\nTables: {", ".join(diff)}\n"""\n\n'
        "from alembic import op\n"
        "from starpulse.board.adapters.policy_chain import replace\n\n"
        f"revision = {revision!r}\n"
        f"down_revision = {down_revision!r}\n\n"
        f"CHANGES = {pprint.pformat(diff, width=110, sort_dicts=False)}\n\n\n"
        'def upgrade() -> None:\n    replace(op.get_bind(), CHANGES, "after")\n\n\n'
        'def downgrade() -> None:\n    replace(op.get_bind(), CHANGES, "before")\n'
    )


def drift_report(expected: Rows, stored: Rows) -> list[str]:
    """One line per table that differs and per row only one side holds, `-` for an expected row and `+` for a stored one."""
    lines: list[str] = []
    for table in _ROW:
        if expected[table] == stored[table]:
            continue
        lines.append(
            f"{TABLE_PREFIX}{table}: the chain records {len(expected[table])} rows, the store holds {len(stored[table])}"
        )
        lines.extend(f"  - {json.dumps(row)}" for row in expected[table] if row not in stored[table])
        lines.extend(f"  + {json.dumps(row)}" for row in stored[table] if row not in expected[table])
    return lines


def _sorted(table: str, held: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = _ORDER.get(table)
    return held if columns is None else sorted(held, key=lambda row: [row[column] for column in columns])


def _ident(table: str, row: dict[str, Any]) -> str:
    return json.dumps([row[column] for column in KEYS[table]])


def _keyed(table: str, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]] | None:
    """The keyed change from `before` to `after`, or None when a key repeats or either side cannot be rebuilt from it in order."""
    old = {_ident(table, row): row for row in before}
    new = {_ident(table, row): row for row in after}
    if len(old) < len(before) or len(new) < len(after):
        return None
    edits = [
        {
            "key": {column: row[column] for column in KEYS[table]},
            "before": {column: value for column, value in row.items() if value != new[key][column]},
            "after": {column: value for column, value in new[key].items() if value != row[column]},
        }
        for key, row in old.items()
        if key in new and row != new[key]
    ]
    parts = {"add": [row for key, row in new.items() if key not in old], "remove": [row for key, row in old.items() if key not in new], "change": edits}
    keyed = {name: held for name, held in parts.items() if held}
    if _moved(table, before, keyed, "after") != after or _moved(table, after, keyed, "before") != before:
        return None
    return keyed


def _moved(table: str, held: list[dict[str, Any]], entry: dict[str, list[dict[str, Any]]], side: str) -> list[dict[str, Any]]:
    if side in entry:
        return entry[side]
    added, removed = ("add", "remove") if side == "after" else ("remove", "add")
    edits = {_ident(table, edit["key"]): edit[side] for edit in entry.get("change", [])}
    gone = {_ident(table, row) for row in entry.get(removed, [])}
    kept = [{**row, **edits.get(_ident(table, row), {})} for row in held if _ident(table, row) not in gone]
    return _sorted(table, [*kept, *entry.get(added, [])])
