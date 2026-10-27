"""The summary tables a test compares: what the store folded as it recorded against what `rebuild_summaries` gives."""

from sqlalchemy import select
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.flow_metrics.adapters.outbound.summaries import SUMMARY_TABLES


def summary_rows(store: HistoryStore) -> dict[str, list[tuple]]:
    """Every column of each summary table but a surrogate `id`, which a rebuild numbers anew; the rows in a stable order."""
    with store.engine.connect() as db:
        return {
            table.name: sorted(
                (tuple(row) for row in db.execute(select(*(column for column in table.c if column.name != "id")))),
                key=repr,
            )
            for table in SUMMARY_TABLES
        }


def assert_matches_rebuild(store: HistoryStore) -> None:
    """The summaries the store holds equal the ones `rebuild_summaries` folds from its raw rows; it rebuilds them."""
    recorded = summary_rows(store)
    store.rebuild_summaries()
    assert summary_rows(store) == recorded
