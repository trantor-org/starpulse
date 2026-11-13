"""The rows a policy is stored as, and the difference between two policies as the data migration that moves one to the other."""

from __future__ import annotations

import json
import pprint
from dataclasses import asdict
from typing import Any

from starpulse.board.model.policy import Exit, Lane, LaneTool, Policy, PolicyRule, Profile, Route, Vocabulary, Watch

__all__ = ["Changes", "Rows", "apply", "changes", "drift_report", "render", "rows"]

Rows = dict[str, list[dict[str, Any]]]
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
    """Each table whose rows differ, with its rows `before` and `after`."""
    return {table: {"before": before[table], "after": after[table]} for table in _ROW if before[table] != after[table]}


def apply(held: Rows, diff: Changes, side: str) -> Rows:
    """`held` with each changed table's rows set to the `side` (`before` or `after`) of `diff`."""
    return {table: diff[table][side] if table in diff else held[table] for table in _ROW}


def render(revision: str, down_revision: str | None, message: str, diff: Changes) -> str:
    """The text of the migration `revision` that applies `diff`; it replaces each changed table with one side's rows."""
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
        lines.append(f"{TABLE_PREFIX}{table}: the chain records {len(expected[table])} rows, the store holds {len(stored[table])}")
        lines.extend(f"  - {json.dumps(row)}" for row in expected[table] if row not in stored[table])
        lines.extend(f"  + {json.dumps(row)}" for row in stored[table] if row not in expected[table])
    return lines


def _sorted(table: str, held: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = _ORDER.get(table)
    return held if columns is None else sorted(held, key=lambda row: [row[column] for column in columns])
