"""The server process reports its resident memory, CPU time, threads, open files and start time as Prometheus gauges."""

import os
from pathlib import Path

from starpulse._internal.server.process_metrics import process_gauges


def _proc(tmp_path: Path, *, resident_pages: int, threads: int, fds: int, utime: int = 0, stime: int = 0) -> Path:
    proc = tmp_path / "proc"
    (proc / "fd").mkdir(parents=True)
    (proc / "statm").write_text(f"90000 {resident_pages} 4000 1 0 8000 0\n")
    (proc / "stat").write_text(f"4242 (star pulse) S 1 1 1 0 -1 0 0 0 0 0 {utime} {stime} 0 0 20 0 19 0 1 0 0\n")
    (proc / "status").write_text(f"Name:\tstarpulse\nThreads:\t{threads}\nVmRSS:\t1 kB\n")
    for n in range(fds):
        (proc / "fd" / str(n)).touch()
    return proc


def test_gauges_report_resident_bytes_threads_open_files_and_start_time(tmp_path: Path) -> None:
    proc = _proc(tmp_path, resident_pages=250, threads=19, fds=7)

    lines = process_gauges(proc, started=1_700_000_000.5).splitlines()

    assert f"process_resident_memory_bytes {250 * os.sysconf('SC_PAGE_SIZE')}" in lines
    assert "process_threads 19" in lines
    assert "process_open_fds 7" in lines
    assert "process_start_time_seconds 1700000000.5" in lines
    assert "# TYPE process_resident_memory_bytes gauge" in lines


def test_gauges_are_left_out_where_the_host_has_no_proc_files(tmp_path: Path) -> None:
    assert process_gauges(tmp_path / "missing", started=1.0) == ""


def test_cpu_seconds_total_sums_user_and_system_ticks_even_when_the_command_name_has_spaces(tmp_path: Path) -> None:
    ticks = os.sysconf("SC_CLK_TCK")
    proc = _proc(tmp_path, resident_pages=1, threads=1, fds=0, utime=3 * ticks, stime=2 * ticks)

    lines = process_gauges(proc, started=1.0).splitlines()

    assert "process_cpu_seconds_total 5.0" in lines
    assert "# TYPE process_cpu_seconds_total counter" in lines
