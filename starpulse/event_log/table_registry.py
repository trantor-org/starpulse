"""Every StarPulse table's class, and the tables each derived family folds from.

A durable table holds rows no event rebuilds; a derived one is dropped, created and refolded when its family's stamp
changes, except the read model's, which has no stamp: its shape changes by a migration; an ephemeral one is rewritten by its owner while it runs; a dead one nothing writes or reads, left declared
until the baseline squash drops it. The search, facets and vectors tables are created outside this chain and left out.
"""

import hashlib
import time
from collections.abc import Iterable, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, Engine, Table, delete, insert, select
from sqlalchemy.schema import CreateIndex, CreateTable

from starpulse.event_log.tables import settings

KINDS = ("durable", "derived", "ephemeral", "dead")


class Family(NamedTuple):
    """The derived tables one stamp covers, and the tables their fold reads."""

    tables: tuple[str, ...]
    reads: tuple[str, ...]


def _t(*names: str) -> tuple[str, ...]:
    return tuple(f"starpulse_{name}" for name in names)


FAMILIES: dict[str, Family] = {
    "read_model": Family(_t("tasks", "task_criteria", "board_keys"), _t("events")),
    "read_model_machines": Family(_t("machine_tasks"), _t("machine_events")),
    "snapshots": Family(_t("snapshots", "snapshot_deltas"), _t("tasks")),
    "task_spend": Family(_t("task_sessions", "task_phase_spend"), _t("signal_folds")),
}
_DURABLE = _t(
    "events", "machine_events", "lane_changes", "signal_folds", "stream_events", "checkpoints", "settings",
    "learned_steps", "scheduler_runs",
    "retired_tasks", "pull_requests", "machine_versions", "machine_active", "policy_versions",
    "policy_active", "task_links", "daily_report",
) + ("github_inbox", "github_inbox_state", "github_reconcile_state")  # the inbox's names are the readers' own
CLASSES: dict[str, str] = {
    **dict.fromkeys(_DURABLE, "durable"),
    **dict.fromkeys((t for family in FAMILIES.values() for t in family.tables), "derived"),
    **dict.fromkeys(_t("worker_state", "leases"), "ephemeral"),
    **dict.fromkeys(_t("step_summaries", "gaps", "task_verdicts"), "dead"),
}


def unclassed(names: Iterable[str]) -> list[str]:
    return sorted(set(names) - set(CLASSES))


def definition(tables: Iterable[Table]) -> str:
    """The DDL that creates `tables` and their indexes: a column or index edit changes it."""
    tables = list(tables)
    return "\n".join(
        [str(CreateTable(table)) for table in tables]
        + sorted(str(CreateIndex(index)) for table in tables for index in table.indexes)
    )


def stamp_of(*inputs: str) -> str:
    """One digest of a family's definition and fold inputs."""
    return hashlib.sha256("\x00".join(inputs).encode()).hexdigest()


def _key(family: str) -> str:
    return f"derived_stamp:{family}"


def is_stamped(db: Connection, family: str, stamp: str) -> bool:
    """Whether the family's tables were folded under `stamp`: a store with no stamp row was not."""
    return db.execute(select(settings.c.value).where(settings.c.key == _key(family))).scalar() == stamp


def clear_stamp(db: Connection, family: str) -> None:
    """Drop the family's stamp: the first write of a refold, which takes the write lock and opens the transaction its
    DDL then runs in, so the tables are swapped in whole or not at all."""
    db.execute(delete(settings).where(settings.c.key == _key(family)))


def swap(db: Connection, family: str, tables: Sequence[Table]) -> None:
    """Drop `tables` and create them again from their metadata, empty, in the caller's transaction: the stamp goes
    first, so the transaction is open before the DDL."""
    clear_stamp(db, family)
    metadata = tables[0].metadata
    metadata.drop_all(db, tables=tables)
    metadata.create_all(db, tables=tables)


def write_stamp(db: Connection, family: str, stamp: str) -> None:
    """Record `stamp` as the one the family was folded under, in the transaction that swaps its tables in."""
    db.execute(insert(settings).values(key=_key(family), value=stamp, updated_at=time.time()))


def stamped(engine: Engine, family: str, tables: Sequence[Table], *inputs: str) -> bool:
    """Whether the family holds the stamp of the definition of `tables` and `inputs`."""
    with engine.connect() as db:
        return is_stamped(db, family, stamp_of(definition(tables), *inputs))


def empty_unless_stamped(engine: Engine, family: str, tables: Sequence[Table], *inputs: str) -> None:
    """Create `tables` again, empty, unless the family holds the stamp of their definition and `inputs`: a family whose
    owner fills it again as it runs. A family stamped so is left as it is."""
    if stamped(engine, family, tables, *inputs):
        return
    with engine.begin() as db:
        swap(db, family, tables)
        write_stamp(db, family, stamp_of(definition(tables), *inputs))
