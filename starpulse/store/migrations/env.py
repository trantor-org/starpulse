"""Alembic's environment for the hub's history schema: online only, on the connection `starpulse.hub` passes in."""

from alembic import context

from starpulse.hub import VERSION_TABLE
from starpulse.store import history  # noqa: F401 - declares the history tables on the shared metadata
from starpulse.store.tables import metadata

context.configure(
    connection=context.config.attributes["connection"], target_metadata=metadata, version_table=VERSION_TABLE
)
with context.begin_transaction():
    context.run_migrations()
