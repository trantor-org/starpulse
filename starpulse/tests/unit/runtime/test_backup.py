"""`starpulse backup`: a copy that passes `integrity_check`, and only the newest `--keep` copies left in the directory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from starpulse.event_log.event_log import EventLog
from starpulse.runtime.backup import main, prune


def _seed_store(directory: Path) -> Path:
    db = directory / "starpulse-history.sqlite"
    EventLog(f"sqlite:///{db}").set_setting("scheduler.enabled", True)
    return db


def test_backup_writes_a_copy_that_passes_integrity_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_store(tmp_path)
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "copies"

    assert main(["--to", str(dest)]) == 0

    (copy,) = dest.glob("starpulse-*.db")
    with sqlite3.connect(copy) as check:
        assert check.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_prune_keeps_the_newest_copies(tmp_path: Path) -> None:
    for name in ("starpulse-20260101T000000.db", "starpulse-20260102T000000.db", "starpulse-20260103T000000.db"):
        (tmp_path / name).touch()

    prune(tmp_path, keep=2)

    assert sorted(p.name for p in tmp_path.glob("starpulse-*.db")) == [
        "starpulse-20260102T000000.db",
        "starpulse-20260103T000000.db",
    ]
