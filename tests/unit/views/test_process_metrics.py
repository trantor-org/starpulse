"""The server process reports its resident memory, CPU time, threads, open files and start time as Prometheus gauges."""

import threading

from starpulse.views.adapters.outbound.process_metrics import process_gauges


def _samples() -> dict[str, float]:
    lines = [line for line in process_gauges().splitlines() if not line.startswith("#")]
    return {name: float(value) for name, value in (line.split() for line in lines)}


def test_gauges_report_resident_bytes_cpu_threads_open_files_and_start_time() -> None:
    samples = _samples()

    assert samples["process_resident_memory_bytes"] > 0
    assert samples["process_cpu_seconds_total"] > 0
    assert samples["process_threads"] >= 1
    assert samples["process_open_fds"] > 0
    assert samples["process_start_time_seconds"] > 1_700_000_000


def test_gauges_keep_their_prometheus_types() -> None:
    text = process_gauges()

    assert "# TYPE process_resident_memory_bytes gauge" in text
    assert "# TYPE process_cpu_seconds_total counter" in text
    assert "# TYPE process_threads gauge" in text


def test_threads_counts_a_thread_started_since_the_last_scrape() -> None:
    before = _samples()["process_threads"]
    release = threading.Event()
    worker = threading.Thread(target=release.wait)
    worker.start()
    try:
        assert _samples()["process_threads"] == before + 1
    finally:
        release.set()
        worker.join()
