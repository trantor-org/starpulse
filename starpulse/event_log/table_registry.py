"""Every StarPulse table's class, and the tables each derived family folds from.

A durable table holds rows no event rebuilds; a derived one is dropped, created and refolded when its family's stamp
changes; an ephemeral one is rewritten by its owner while it runs. A dead table is read by nothing and leaves with the
baseline squash. The GitHub inbox tables (`github_inbox*`, `github_reconcile_state`) and the search, facets and vectors
tables are created outside this chain and left out.
"""

import hashlib
import time
from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import Connection, Table, delete, insert, select
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
    "summaries": Family(_t("step_summaries", "cases", "lane_intervals", "lanes"), _t("machine_events", "lane_changes")),
    "read_model": Family(_t("tasks", "task_criteria", "machine_tasks"), _t("events", "machine_events")),
    "snapshots": Family(_t("snapshots", "snapshot_deltas", "claim_expiries"), _t("tasks")),
    "signals": Family(_t("signal_folds", "answers"), _t("signals")),
}
_DURABLE = _t(
    "events", "machine_events", "lane_changes", "signals", "stream_events", "checkpoints", "settings", "gaps",
    "breaking_changes", "breaking_change_detections", "task_verdicts", "learned_steps", "scheduler_runs",
    "retired_tasks", "pull_requests", "machine_versions", "machine_active", "reader_floor", "policy_exits",
    "policy_lanes", "policy_profiles", "policy_routes", "policy_rules", "policy_tools", "policy_vocabularies",
    "policy_watches",
)
CLASSES: dict[str, str] = {
    **dict.fromkeys(_DURABLE, "durable"),
    **dict.fromkeys((t for family in FAMILIES.values() for t in family.tables), "derived"),
    **dict.fromkeys(_t("worker_state", "leases"), "ephemeral"),
    **dict.fromkeys(_t("source_instances", "forward_instances"), "dead"),
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


def write_stamp(db: Connection, family: str, stamp: str) -> None:
    """Record `stamp` as the one the family was folded under, in the transaction that swaps its tables in."""
    db.execute(insert(settings).values(key=_key(family), value=stamp, updated_at=time.time()))
