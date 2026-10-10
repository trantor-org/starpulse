"""The soak's rules: durations, upward trends, the verdict, the process reads and the run's schedule."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import seeded_server

_BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(_BENCH))  # soak.py imports the page driver beside it
_spec = importlib.util.spec_from_file_location("soak", _BENCH / "soak.py")
assert _spec and _spec.loader
soak = sys.modules["soak"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soak)

MB = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("text", "seconds"), [("90", 90), ("45s", 45), ("10m", 600), ("60m", 3600), ("24h", 86400), ("1.5h", 5400)]
)
def test_a_duration_reads_in_seconds_minutes_or_hours(text, seconds):
    assert soak.parse_duration(text) == seconds


def test_a_duration_that_is_not_one_is_refused():
    with pytest.raises(ValueError, match="duration"):
        soak.parse_duration("soon")


def _series(metric: str, values: list[float]) -> list[dict]:
    return [{"t": 300.0 * i, metric: v} for i, v in enumerate(values)]


def test_a_floor_that_keeps_rising_is_an_upward_trend():
    # a leak: each GC leaves 10 MB more behind than the last
    heap = [(100 + 10 * i) * MB for i in range(12)]
    [trend] = soak.trends(_series("heap", heap), ["heap"])
    assert trend.judged and trend.upward
    assert trend.rise > trend.limit


def test_a_sawtooth_around_a_steady_floor_is_not_a_trend():
    # garbage collection: the heap climbs 30 MB between collections and falls back to the same floor
    heap = [(100 + 30 * (i % 3)) * MB for i in range(12)]
    [trend] = soak.trends(_series("heap", heap), ["heap"])
    assert trend.judged and not trend.upward


def test_a_rise_inside_the_noise_allowance_is_not_a_trend():
    nodes = [2000 + (i // 4) * 20 for i in range(12)]  # 40 nodes over the run, allowance is 100
    [trend] = soak.trends(_series("nodes", nodes), ["nodes"])
    assert trend.judged and not trend.upward


def test_a_run_too_short_to_judge_is_marked_unjudged_and_never_upward():
    [trend] = soak.trends(_series("heap", [100 * MB, 900 * MB, 1700 * MB]), ["heap"])
    assert not trend.judged and not trend.upward


def test_a_metric_the_page_did_not_report_is_skipped():
    assert soak.trends(_series("heap", [1.0] * 12), ["heap", "rss"]) == soak.trends(
        _series("heap", [1.0] * 12), ["heap"]
    )


def test_the_run_fails_on_a_probe_over_budget_or_an_upward_trend():
    ok = soak.Row("open a task's modal", "interaction", 50.0, [10.0])
    slow = soak.Row("open a task's modal", "interaction", 50.0, [90.0])
    rising = soak.Trend("rss", 100.0, 900.0, 800.0, 20.0, judged=True)
    flat = soak.Trend("rss", 100.0, 100.0, 0.0, 20.0, judged=True)

    assert soak.failures([soak.probe_record(0, [ok])], [flat]) == []
    over = soak.failures([soak.probe_record(0, [ok]), soak.probe_record(600, [slow])], [flat])
    assert len(over) == 1 and "600" in over[0] and "open a task's modal" in over[0]
    assert len(soak.failures([soak.probe_record(0, [ok])], [rising])) == 1


def test_the_process_reads_rss_threads_and_open_files_of_a_pid():
    stats = soak.process_stats(os.getpid())
    assert stats["rss"] > MB
    assert stats["threads"] >= 1
    assert stats["fds"] >= 3


class FakeTarget:
    """A page and server that answer at once; `leak` adds 50 MB of RSS a sample, `slow` fails every probe."""

    def __init__(self, *, leak: bool = False, slow: bool = False) -> None:
        self.leak, self.slow, self.sampled, self.probed = leak, slow, 0, 0

    def sample(self) -> dict:
        self.sampled += 1
        return {"heap": 100.0 * MB, "rss": (200 + 50 * self.sampled * self.leak) * MB}

    def probe(self) -> list:
        self.probed += 1
        return [soak.Row("open a task's modal", "interaction", 50.0, [99.0 if self.slow else 5.0])]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run(target: FakeTarget, duration: float = 3600, interval: float = 600, every: float = 300) -> dict:
    clock = Clock()
    return soak.run(target, duration, interval, every, clock=lambda: clock.now, sleep=clock.sleep)


def test_a_one_hour_run_probes_every_interval_and_samples_between():
    target = FakeTarget()
    report = _run(target)
    assert [p["t"] for p in report["probes"]] == [0, 600, 1200, 1800, 2400, 3000]
    assert [s["t"] for s in report["samples"]] == [300 * i for i in range(13)]
    assert (target.probed, target.sampled) == (6, 13)
    assert report["failures"] == []


def test_a_probe_over_budget_is_recorded_as_a_failure():
    report = _run(FakeTarget(slow=True))
    assert len(report["failures"]) == 6
    assert report["probes"][0]["rows"][0]["over"] is True


def test_a_leaking_server_is_recorded_as_an_upward_trend():
    report = _run(FakeTarget(leak=True))
    [rss] = [t for t in report["trends"] if t["metric"] == "rss"]
    assert rss["upward"] is True
    assert any("rss" in f for f in report["failures"])


def test_the_exit_status_is_nonzero_exactly_when_the_report_has_failures(tmp_path):
    out = tmp_path / "soak.json"
    assert soak.finish(_run(FakeTarget()), out) == 0
    assert json.loads(out.read_text())["failures"] == []
    assert soak.finish(_run(FakeTarget(slow=True)), out) == 1
    assert len(json.loads(out.read_text())["failures"]) == 6


class Flaky(FakeTarget):
    """Fails the calls whose 1-based number is in `bad`, as a restarting server fails the probes it overlaps."""

    def __init__(self, *, bad_probes: tuple[int, ...] = (), dead: bool = False) -> None:
        super().__init__()
        self.bad_probes, self.dead = bad_probes, dead

    def sample(self) -> dict:
        if self.dead:
            raise TimeoutError("page.evaluate timed out")
        return super().sample()

    def probe(self) -> list:
        if self.dead or self.probed + 1 in self.bad_probes:
            self.probed += 1
            raise ConnectionRefusedError("the server is restarting")
        return super().probe()


def test_a_probe_that_raises_is_a_failure_and_the_run_goes_on():
    report = _run(Flaky(bad_probes=(2,)))
    assert len(report["probes"]) == 5
    assert len(report["samples"]) == 13
    assert len(report["failures"]) == 1
    assert "probe" in report["failures"][0] and "ConnectionRefusedError" in report["failures"][0]


def test_three_failed_calls_in_a_row_end_the_run():
    report = _run(Flaky(dead=True))
    assert report["probes"] == [] and report["samples"] == []
    assert len(report["failures"]) == 3
    assert all("TimeoutError" in f or "ConnectionRefusedError" in f for f in report["failures"])


class Hold:
    """The feeder's clock without the wait: `wait` advances it and says the hold is over once `seconds` have passed."""

    def __init__(self, seconds: float) -> None:
        self.now, self.seconds = 0.0, seconds

    def wait(self, delay: float) -> bool:
        self.now += delay
        return self.now >= self.seconds


@pytest.fixture
def seeded(tmp_path):
    # `ci/preview.toml` names its board `ci.demo_workspace`, which needs the repository root on the import path
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT))
        server, feed, tasks = seeded_server.build(0, tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, feed, tasks
    server.shutdown()


def _events(server):
    """The names of the events a client on the server's stream is sent, one at a time, until the stream goes quiet."""
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    conn.request("GET", "/api/events", headers={"accept": "text/event-stream"})
    response = conn.getresponse()
    try:
        while line := response.fp.readline():
            if line.startswith(b"event:"):
                yield line[6:].strip().decode()
    except TimeoutError:
        return
    finally:
        conn.close()


def test_the_replay_feeds_a_stream_client_one_task_event_a_step_at_the_rate(seeded):
    server, feed, tasks = seeded
    stream = _events(server)
    assert next(stream) == "snapshot"  # the client is attached to the feed before the first step

    sent = seeded_server.replay(feed, tasks, 8.0, (hold := Hold(5.0)).wait, lambda: hold.now)

    assert sent == 40  # 8 a second for a 5 second hold
    received = 0
    for name in stream:
        received += name == "task"
        if received == sent:
            break
    assert received == sent


def test_the_replay_stops_when_the_run_does(seeded):
    server, feed, tasks = seeded
    stop = threading.Event()
    feeder = threading.Thread(target=seeded_server.replay, args=(feed, tasks, 200.0, stop.wait), daemon=True)
    before = feed.rev
    feeder.start()
    deadline = time.monotonic() + 10
    while feed.rev == before and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    feeder.join(timeout=5)

    assert feed.rev > before  # it was feeding
    assert not feeder.is_alive()


def test_the_replay_rate_is_a_multiple_of_the_live_rate_and_the_default_passes_a_day_through_a_4_hour_hold():
    assert soak.replay_rate(1) == pytest.approx(soak.LIVE_EVENTS_PER_DAY / 86400)
    assert soak.replay_rate(12) == pytest.approx(2 * soak.replay_rate(6))
    assert soak.replay_rate(soak.REPLAY_MULTIPLE) * 4 * 3600 == pytest.approx(soak.LIVE_EVENTS_PER_DAY)


def test_the_soak_starts_a_seeded_server_replays_into_it_and_tears_it_down():
    with soak.seeded(3000) as server:
        assert server.pid > 0 and server.failure() is None
        with urllib.request.urlopen(f"{server.base}/api/snapshot", timeout=30) as response:
            assert response.status == 200
        port = int(server.base.rsplit(":", 1)[1])
        assert soak.listening_pid(port) == server.pid  # the process the soak reads /proc for is the server itself
        time.sleep(1)

    assert server.replayed > 0
    assert not Path(f"/proc/{server.pid}").exists()
    assert not server.scratch.exists()


def test_a_seeded_server_that_dies_during_the_run_is_a_failure_of_the_run():
    with soak.seeded(1) as server:
        assert server.pid > 0  # pid 0 would signal the whole process group
        os.kill(server.pid, signal.SIGKILL)
        server.proc.wait(timeout=10)
        assert "exited" in server.failure()


def test_a_seeded_soak_without_the_built_page_says_how_to_build_it(tmp_path, monkeypatch):
    monkeypatch.setattr(soak, "REPO", tmp_path)
    with pytest.raises(RuntimeError, match="not built.*pnpm"):
        soak.require_built_page()


def test_the_first_sample_follows_the_first_probe_so_the_page_it_measures_has_visited_its_views():
    calls: list[str] = []

    class Logged(FakeTarget):
        def sample(self) -> dict:
            calls.append("sample")
            return super().sample()

        def probe(self) -> list:
            calls.append("probe")
            return super().probe()

    _run(Logged())
    assert calls[:2] == ["probe", "sample"]
