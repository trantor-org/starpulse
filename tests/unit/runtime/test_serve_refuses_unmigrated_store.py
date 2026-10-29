"""`starpulse serve` refuses, before it listens, a store `starpulse migrate` has not brought to its schema."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest
from starpulse.runtime import server
from starpulse.runtime.config import load


def test_serve_exits_naming_migrate_when_the_store_is_not_migrated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "starpulse.toml"
    config_file.write_text(f'database_url = "sqlite:///{tmp_path / "store.sqlite"}"\n')
    args = argparse.Namespace(config=config_file, hours=1)

    with pytest.raises(SystemExit) as exited:
        server.refuse_unassemblable(argparse.ArgumentParser(), args, load(config_file), SimpleNamespace(run_safe=()))

    assert exited.value.code == 1
    assert "starpulse migrate" in capsys.readouterr().err
