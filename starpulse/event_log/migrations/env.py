"""Alembic's environment for the history schema: online only, on the connection `eventlog.migrate` or the hub passes in."""

from alembic import context
from starpulse.event_log.tables import VERSION_TABLE, metadata
from starpulse.flow_metrics.adapters.outbound import history  # noqa: F401 - declares the history tables on the shared metadata

context.configure(
    connection=context.config.attributes["connection"], target_metadata=metadata, version_table=VERSION_TABLE
)
with context.begin_transaction():
    context.run_migrations()
