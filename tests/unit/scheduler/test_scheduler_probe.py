"""The built-in probe reads the host's CPU and memory through psutil, so a fresh install needs no monitoring stack."""

from types import SimpleNamespace

import psutil
import pytest
from starpulse.scheduler.adapters.probe import LocalProbe


def test_memory_is_psutils_used_share_of_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(percent=75.0))

    assert LocalProbe()()["memory"] == 75.0


def test_cpu_is_psutils_busy_share_since_the_previous_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    readings = iter([0.0, 20.0, 50.0])  # one for construction, then one per call
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: next(readings))
    probe = LocalProbe()

    assert probe()["cpu"] == 20.0
    assert probe()["cpu"] == 50.0


def test_a_live_host_reads_percentages() -> None:
    reading = LocalProbe()()

    assert 0 <= reading["cpu"] <= 100
    assert 0 < reading["memory"] <= 100
