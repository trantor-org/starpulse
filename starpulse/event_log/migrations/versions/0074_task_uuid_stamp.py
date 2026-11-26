"""Give every Task stream of History that has no UUID the v5 UUID of its board and key.

Each such stream takes one `FieldsEdited` that sets `meta.uuid` to the v5 of (board, canonical `TASK-N` key), the value
a Task file of that board and key already derives; a stream that has one is left alone, so a rerun stamps none. The
board's name is the one `starpulse migrate` passes (`alembic_config(board=)`): a store with an unstamped stream and no
board name is refused rather than recorded as stamped. A rebuild of the read model fills `starpulse_tasks.uuid`,
`starpulse_board_keys` and each `task_uuid` from the stamp.

Revision ID: 0074
Revises: 0073
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.event_log.store.tables import stream_events

revision: str = "0074"
down_revision: str | tuple[str, ...] | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    board = op.get_context().config.attributes.get("board")
    store = EventStore(bind.engine)
    tasks = bind.execute(
        sa.select(stream_events.c.subject_id).where(stream_events.c.subject_kind == "task").distinct()
    ).scalars().all()
    for task in tasks:
        events = store.read_in(bind, "task", task)
        if replay(events).get("meta", {}).get("uuid"):
            continue
        if not board:
            raise RuntimeError(f"{task} has no UUID and no board name is known: run `starpulse migrate --config FILE`")
        stamp = str(uuid.uuid5(uuid.NAMESPACE_URL, f"starpulse:{board}:{task.upper()}"))
        change = NewEvent("FieldsEdited", {"meta": {"uuid": stamp}}, "operator", "native-board")
        store.append("task", task, events[-1].version, [change], connection=bind)


def downgrade() -> None:
    raise NotImplementedError("a stamp is an event, which a stream keeps")
