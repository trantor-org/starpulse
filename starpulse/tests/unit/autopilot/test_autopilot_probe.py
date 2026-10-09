"""The built-in probe reads the host's CPU and memory from `/proc`, so a fresh install needs no monitoring stack."""

from pathlib import Path

from starpulse._internal.autopilot.probe import LocalProbe


def _proc(tmp_path: Path, *, idle: int, busy: int, available_kb: int, total_kb: int = 1000) -> Path:
    (tmp_path / "stat").write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0 0 0\n")
    (tmp_path / "meminfo").write_text(f"MemTotal:       {total_kb} kB\nMemFree: 5 kB\nMemAvailable:   {available_kb} kB\n")
    return tmp_path


def test_memory_is_the_share_of_the_host_not_available(tmp_path: Path) -> None:
    proc = _proc(tmp_path, idle=800, busy=200, available_kb=250)

    assert LocalProbe(proc)()["memory"] == 75.0


def test_the_first_cpu_reading_is_the_busy_share_since_boot(tmp_path: Path) -> None:
    proc = _proc(tmp_path, idle=800, busy=200, available_kb=500)

    assert LocalProbe(proc)()["cpu"] == 20.0


def test_a_later_cpu_reading_is_the_busy_share_since_the_last_one(tmp_path: Path) -> None:
    probe = LocalProbe(_proc(tmp_path, idle=800, busy=200, available_kb=500))
    probe()

    _proc(tmp_path, idle=1000, busy=400, available_kb=500)  # 200 busy and 200 idle ticks since

    assert probe()["cpu"] == 50.0


def test_a_reading_with_no_ticks_since_the_last_one_repeats_it(tmp_path: Path) -> None:
    probe = LocalProbe(_proc(tmp_path, idle=800, busy=200, available_kb=500))
    first = probe()["cpu"]

    assert probe()["cpu"] == first
