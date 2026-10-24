"""Cursor transcripts ingested into a real event log: a re-read adds nothing and an old transcript is left alone."""

import os
import shutil
from pathlib import Path

from starpulse._internal.config.analytics import Analytics
from starpulse._internal.harnesses.cursor import ingest
from starpulse._internal.harnesses.telemetry import TelemetryLog
from starpulse.event_log.event_log import EventLog
from starpulse.tests.unit.harnesses.test_cursor import ANALYTICS, KEYS, SESSION, TRANSCRIPT

NOW = 1_800_000_000.0


def projects(tmp_path: Path, age_hours: float) -> Path:
    target = tmp_path / "projects" / "home-adinb-trantor" / "agent-transcripts" / SESSION
    shutil.copytree(TRANSCRIPT.parent, target)
    os.utime(target / TRANSCRIPT.name, (NOW - age_hours * 3600,) * 2)
    return tmp_path / "projects"


def telemetry_at(tmp_path: Path) -> TelemetryLog:
    return TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))


def test_a_transcript_read_twice_is_stored_once(tmp_path: Path) -> None:
    telemetry, root = telemetry_at(tmp_path), projects(tmp_path, age_hours=1)

    assert ingest(root, telemetry, keys=KEYS, analytics=ANALYTICS, now=NOW) == 1
    stored = telemetry.read()
    assert ingest(root, telemetry, keys=KEYS, analytics=ANALYTICS, now=NOW) == 1

    assert stored
    assert len(TelemetryLog(telemetry._log).read()) == len(stored)


def test_a_transcript_older_than_the_window_is_not_read(tmp_path: Path) -> None:
    telemetry, root = telemetry_at(tmp_path), projects(tmp_path, age_hours=72)

    assert ingest(root, telemetry, keys=KEYS, analytics=Analytics(), hours=48, now=NOW) == 0
    assert telemetry.read() == []
