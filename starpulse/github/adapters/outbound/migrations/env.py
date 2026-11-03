"""Alembic's environment for the inbox schema: online only, on the connection `migrate_chain` passes in."""

from alembic import context
from starpulse.github.adapters.outbound.inbox import VERSION_TABLE, metadata

context.configure(
    connection=context.config.attributes["connection"], target_metadata=metadata, version_table=VERSION_TABLE
)
with context.begin_transaction():
    context.run_migrations()
