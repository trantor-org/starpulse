"""Alembic's environment for the hub's history schema: online only, on the connection `starpulse._internal.api.hub` passes in."""

from alembic import context

from starpulse._internal.eventlog import history  # noqa: F401 - declares the history tables on the shared metadata
from starpulse._internal.eventlog.tables import VERSION_TABLE, metadata

context.configure(
    connection=context.config.attributes["connection"], target_metadata=metadata, version_table=VERSION_TABLE
)
with context.begin_transaction():
    context.run_migrations()
