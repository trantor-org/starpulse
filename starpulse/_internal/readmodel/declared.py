"""A deployment's declared fields: `[board.fields.<name>]` gives each a `type` and whether it is `queried`.

A queried field gets a virtual generated column over the `fields` JSON and a partial index on unarchived rows, so
a query by it is an index seek however many Tasks the board holds.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text

_NAME = re.compile(r"[a-z][a-z0-9_]*")
TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,)}


class BadDeclaration(ValueError):
    """`[board.fields]` names a field badly or gives it a type StarPulse does not know."""


class UndeclaredField(ValueError):
    """A Task carries a field `[board.fields]` does not declare."""


class MistypedField(ValueError):
    """A field's value is not of the type `[board.fields]` declares."""


@dataclass(frozen=True)
class Declared:
    name: str
    type: str
    queried: bool

    @property
    def column(self) -> str:
        return f"field_{self.name}"


def declared_fields(board: Mapping[str, object]) -> dict[str, Declared]:
    """The fields the `[board]` table declares, by name; none when it declares none."""
    raw = board.get("fields", {})
    if not isinstance(raw, Mapping):
        raise BadDeclaration("[board.fields] must be a table")
    declared: dict[str, Declared] = {}
    for name, spec in raw.items():
        if not _NAME.fullmatch(name):
            raise BadDeclaration(f"field name {name!r} must be lower snake case")
        if not isinstance(spec, Mapping) or spec.get("type") not in TYPES:
            raise BadDeclaration(f"field {name!r} needs a type of {sorted(TYPES)}")
        declared[name] = Declared(name, spec["type"], bool(spec.get("queried", False)))
    return declared


def check_fields(declared: Mapping[str, Declared], fields: Mapping[str, Any]) -> None:
    """Raise when `fields` carries a name `declared` lacks or a value of the wrong type."""
    for name, value in fields.items():
        if name not in declared:
            raise UndeclaredField(f"field {name!r} is not declared in [board.fields]")
        if isinstance(value, bool) != (declared[name].type == "boolean") or not isinstance(
            value, TYPES[declared[name].type]
        ):
            raise MistypedField(f"field {name!r} must be a {declared[name].type}, got {value!r}")


def ensure_columns(engine: Engine, declared: Mapping[str, Declared]) -> None:
    """Give every queried field its generated column and partial index; a field that has them keeps them."""
    with engine.begin() as db:
        have = {row[1] for row in db.execute(text("PRAGMA table_xinfo(starpulse_tasks)"))}
        for field in (field for field in declared.values() if field.queried):
            if field.column not in have:
                db.execute(
                    text(
                        f"ALTER TABLE starpulse_tasks ADD COLUMN {field.column} "
                        f"GENERATED ALWAYS AS (json_extract(fields, '$.{field.name}')) VIRTUAL"
                    )
                )
            db.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_starpulse_tasks_{field.column} "
                    f"ON starpulse_tasks ({field.column}) WHERE archived = 0"
                )
            )
