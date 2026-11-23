"""Nothing reads the signals table: folds advance at ingest from the ledger in `starpulse_signal_folds`.

The table itself stays, classed dead in the registry, and a later release drops it: the release before this one still reads it.

The `steps`, `cost` and `spend` rows of the folds keep their results, which still serve the windows they cover; their
`folded_through`, a signals rowid until now, is a revision of the folds' own counter from here on, so the counter and the
skill-cost cursor start at the highest one. The rows of the views that are gone (`health`, `runs`, `cases`,
`trace_cases`), the stored answers (each answer is read again under the new views) and the old cursor are deleted.

Revision ID: 0063
Revises: 0062
"""

import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
CONTRACT = True

_GONE = ("health", "runs", "cases", "trace_cases")
_STAMP = "derived_stamp:signals"


def _settings() -> sa.Table:
    return sa.table("starpulse_settings", sa.column("key"), sa.column("value", sa.JSON), sa.column("updated_at"))


def upgrade() -> None:
    db = op.get_bind()
    inspector = sa.inspect(db)
    settings = _settings()
    if inspector.has_table("starpulse_signal_folds"):
        folds = sa.table("starpulse_signal_folds", sa.column("view"), sa.column("folded_through"))
        db.execute(sa.delete(folds).where(folds.c.view.in_(_GONE)))
        through = db.execute(sa.select(sa.func.max(folds.c.folded_through))).scalar() or 0
        for key in ("signal_folds_revision", "skill_cost_cursor") if through else ():
            db.execute(sa.delete(settings).where(settings.c.key == key))
            db.execute(sa.insert(settings).values(key=key, value=through, updated_at=0.0))
    if inspector.has_table("starpulse_answers"):
        db.execute(sa.delete(sa.table("starpulse_answers")))
    db.execute(sa.delete(settings).where(settings.c.key.in_(("signal_folds_cursor", _STAMP))))


def downgrade() -> None:
    db = op.get_bind()
    folds = sa.table("starpulse_signal_folds", sa.column("view"))
    db.execute(sa.delete(folds).where(folds.c.view.in_(("ledger", "counted"))))
    settings = _settings()
    db.execute(sa.delete(settings).where(settings.c.key.in_(("signal_folds_revision", "skill_cost_cursor"))))
