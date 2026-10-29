"""Stores a `serve` test opens: `serve` runs its admission in a child process, which the conftest shim cannot patch."""

from pathlib import Path

from sqlalchemy import create_engine
from starpulse.event_log.migrate import migrate
from starpulse.event_log.opening import database_url
from starpulse.runtime.config import load


def migrate_config_store(config: Path) -> None:
    """Bring the store the TOML `config` names to its schema, as `starpulse migrate` does."""
    engine = create_engine(database_url(load(config).database_url, config.parent))
    migrate(engine)
    engine.dispose()
