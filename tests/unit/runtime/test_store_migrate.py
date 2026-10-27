"""`starpulse migrate --config FILE`: a fresh store is brought to its schema and summaries; a second run changes no schema."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from starpulse.runtime import store_migrate


def _schema(url: str) -> list[tuple[str]]:
    with create_engine(url).connect() as db:
        return [tuple(row) for row in db.execute(text("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"))]


def test_migrate_brings_a_fresh_store_up_and_a_second_run_exits_zero_with_no_schema_change(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "{url}"\n')

    assert store_migrate.main(["--config", str(config)]) == 0
    migrated = _schema(url)
    assert migrated

    assert store_migrate.main(["--config", str(config)]) == 0
    assert _schema(url) == migrated
