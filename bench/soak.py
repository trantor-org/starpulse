"""Soak: hold the live page open idle for hours and fail on degradation.

The budget is trantor ADR "StarPulse Holds a Latency Budget on Every Request and Frame"; this is its endurance half.
One Chrome tab opens the page and then sits untouched. Two things happen on a schedule:

- every ``--sample-every``: a sample of the tab (JS heap after a garbage collection, DOM nodes, event listeners,
  animation frames per second over 5 idle seconds, the share of those seconds the renderer was busy) and of the server
  process (RSS, threads, open files);
- every ``--interval``: a probe of the budget, the page's read routes and event stream timed from outside and the task
  modal opened and closed three times on the Kanban, then the tab returns to the view it was on. The modal is opened
  and closed every probe so growth per open shows up, which an untouched tab would not reveal.

The run fails (exit 1) when any probe row's p95 is over its budget, or when a sampled resource trends upward: the
lowest value in the run's last third sits above the lowest in its first third by more than the metric's allowance. The
lowest value ignores the sawtooth of garbage collection and a busy moment, and still catches a leak, which raises it.
The report (``--report FILE``) holds every probe, every sample, every trend and each failure.

Run it from the repository root with ``uv run --group bench python bench/soak.py <url> --duration 24h --report FILE``.
The server's process is found again at every sample from the URL's port on this host, so a restart shows as a new pid;
``--pid`` pins one, and a server on another host reports the page's resources only. A sample or probe that fails (a
restart overlapping it) is a failure of the run; three in a row end it.

With no URL the run starts ``ci/seeded_server.py`` itself, on a free port in a scratch directory, and feeds it a
replayed event stream for the whole hold at ``--replay-multiple`` times the live rate (``bench/README.md``). Its pid is
the one every sample carries, and it is ended on the way out.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import page_latency as pl

Row = pl.Row

MB = 1024 * 1024
#: Seconds the tab is watched, untouched, for the frame count and the renderer's busy share.
IDLE_WINDOW_S = 5
#: Tasks whose modal a probe opens, and reads of each route it times.
PROBE_SAMPLES = 3
#: Failed calls in a row that end a run: a page that is gone, not a server that is restarting.
MAX_ERRORS = 3
#: A trend needs a first and a last third with a couple of samples each.
MIN_SAMPLES = 6
#: Events the live instance's event log takes a day: 14,497 in the 24 hours to 2026-10-10 09:30 MST and 11,075 a day over
#: the 7 before (1,312 and 1,249 of them lane changes). The tab is sent the changes these make.
LIVE_EVENTS_PER_DAY = 14_500
#: The default replay, a multiple of that rate: a 4 hour hold passes 24 / 4 days' worth, about a day of events.
REPLAY_MULTIPLE = 6.0
#: Seconds the seeded server has to seed its board and name its port.
STARTUP_S = 120
#: The lanes the seeded board's what-if reads, spelled as its lane ids.
SEEDED_WHAT_IF = ("in_progress", "review")
REPO = Path(__file__).resolve().parents[1]

#: Per sampled metric: the rise of its floor, as a share of its first floor or in its own unit if that is more, that is
#: still noise. The heap and RSS grow while a page warms up; frames per second only grow when a loop is started twice.
ALLOWANCE: dict[str, tuple[float, float]] = {
    "heap": (0.10, 5 * MB),
    "nodes": (0.05, 100),
    "listeners": (0.05, 50),
    "frames_per_s": (0.25, 5),
    "rss": (0.10, 20 * MB),
    "threads": (0.10, 2),
    "fds": (0.10, 5),
}


@dataclass
class Trend:
    """How one metric's floor moved between the first third of the run and the last."""

    metric: str
    first_floor: float
    last_floor: float
    rise: float
    limit: float
    judged: bool

    @property
    def upward(self) -> bool:
        return self.judged and self.rise > self.limit


def parse_duration(text: str) -> float:
    """Seconds in ``90``, ``45s``, ``10m`` or ``24h``."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", text.strip())
    if not match:
        raise ValueError(f"duration {text!r} is not a number of seconds, minutes (10m) or hours (24h)")
    return float(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[match[2]]


def trends(samples: Sequence[dict], metrics: Sequence[str] = tuple(ALLOWANCE)) -> list[Trend]:
    """One trend per metric the samples carry; a run under ``MIN_SAMPLES`` samples is returned unjudged."""
    found = []
    for metric in metrics:
        values = [s[metric] for s in samples if metric in s]
        if not values:
            continue
        third = len(values) // 3
        if len(values) < MIN_SAMPLES:
            found.append(Trend(metric, 0.0, 0.0, 0.0, 0.0, judged=False))
            continue
        first, last = min(values[:third]), min(values[-third:])
        share, floor = ALLOWANCE[metric]
        found.append(Trend(metric, first, last, last - first, max(share * first, floor), judged=True))
    return found


def probe_record(t: float, rows: Sequence[Row]) -> dict:
    return {
        "t": t,
        "rows": [
            {
                "name": r.name,
                "kind": r.kind,
                "n": len(r.samples),
                "p50": r.p50,
                "p95": r.p95,
                "budget": r.budget,
                "over": r.over,
            }  # fmt: skip
            for r in rows
        ],
    }


def failures(probes: Sequence[dict], found: Sequence[Trend]) -> list[str]:
    """Each probe row over its budget or without a sample, and each metric trending upward."""
    out = []
    for probe in probes:
        for row in probe["rows"]:
            if row["n"] == 0:
                out.append(f"probe at {probe['t']:.0f} s: {row['name']} was not timed")
            elif row["over"]:
                out.append(
                    f"probe at {probe['t']:.0f} s: {row['name']} p95 {row['p95']:.1f} ms over {row['budget']:.1f}"
                )
    out.extend(
        f"{t.metric} trends upward: floor {t.first_floor:g} to {t.last_floor:g}, rose {t.rise:g}, allowed {t.limit:g}"
        for t in found
        if t.upward
    )
    return out


def process_stats(pid: int) -> dict[str, int]:
    """A process's resident bytes, thread count and open file descriptors, read from /proc."""
    status = Path(f"/proc/{pid}/status").read_text()
    rss_kb = int(re.search(r"^VmRSS:\s+(\d+) kB", status, re.M)[1])  # type: ignore[index]
    threads = int(re.search(r"^Threads:\s+(\d+)", status, re.M)[1])  # type: ignore[index]
    return {"rss": rss_kb * 1024, "threads": threads, "fds": len(os.listdir(f"/proc/{pid}/fd"))}


def listening_pid(port: int) -> int | None:
    """The process on this host listening on a TCP port, or None."""
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:  # 0A is LISTEN
                inodes.add(f"socket:[{fields[9]}]")
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if any(os.readlink(fd) in inodes for fd in map(str, proc.joinpath("fd").iterdir())):
                return int(proc.name)
        except OSError:
            continue
    return None


def replay_rate(multiple: float) -> float:
    """Events a second for `multiple` times the live rate."""
    return multiple * LIVE_EVENTS_PER_DAY / 86400


@dataclass
class SeededServer:
    """The seeded server this run started: where it answers, its process and what it was fed."""

    base: str
    proc: subprocess.Popen
    scratch: Path
    replayed: int = 0

    @property
    def pid(self) -> int:
        return self.proc.pid

    def failure(self) -> str | None:
        """Why the server is gone, or None while it runs: a soak of a server that died has nothing to judge."""
        code = self.proc.poll()
        return None if code is None else f"the seeded server exited with status {code}"


def _port_line(proc: subprocess.Popen) -> str:
    """The URL the seeded server names on its first line, once it has seeded its board."""
    assert proc.stdout is not None
    watchdog = threading.Timer(STARTUP_S, proc.kill)
    watchdog.start()
    try:
        line = proc.stdout.readline()
    finally:
        watchdog.cancel()
    if not (match := re.fullmatch(r"seeded StarPulse on :(\d+)\n", line)):
        raise RuntimeError(f"the seeded server did not name its port in {STARTUP_S} s (exit {proc.poll()}): {line!r}")
    return f"http://127.0.0.1:{match[1]}"


def _stop(proc: subprocess.Popen) -> int:
    """End the server and return how many events it replayed, as it reports on its way out."""
    if proc.poll() is None:
        proc.terminate()
    try:
        out, _ = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    match = re.search(r"replayed (\d+) events", out or "")
    return int(match[1]) if match else 0


def require_built_page() -> None:
    """Refuse a seeded run before it starts when the page it would draw is not built, as a fresh checkout's is not."""
    if not (REPO / "starpulse" / "static" / "index.html").is_file():
        raise RuntimeError(
            "the page is not built, so the seeded server has nothing to serve: "
            "pnpm --dir starpulse/web install --frozen-lockfile && pnpm --dir starpulse/web run build"
        )


@contextlib.contextmanager
def seeded(multiple: float) -> Iterator[SeededServer]:
    """Run `ci/seeded_server.py` on a free port in a scratch directory, replaying `multiple` times the live rate.

    The server is this run's own child, so its process is the one sampled and no other run shares its state. It is
    ended, and its directory removed, on the way out.
    """
    with tempfile.TemporaryDirectory(prefix="starpulse-soak-") as scratch:
        command = [sys.executable, "-m", "ci.seeded_server", "--port", "0", "--dir", scratch]
        command += ["--replay-rate", str(replay_rate(multiple))]
        proc = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE, text=True)
        server = SeededServer("", proc, Path(scratch))
        try:
            server.base = _port_line(proc)
            yield server
        finally:
            server.replayed = _stop(proc)


class Target(Protocol):
    def sample(self) -> dict: ...

    def probe(self) -> list[Row]: ...


def run(
    target: Target,
    duration: float,
    interval: float,
    every: float,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Sample every ``every`` seconds and probe every ``interval`` until ``duration``, ending on a last sample.

    A call that raises (the server is restarting, the page stopped answering) is recorded as a failure and the run goes
    on, so a deploy mid-night costs one probe and not the night; ``MAX_ERRORS`` failed calls in a row end it.
    """
    start = clock()
    probes: list[dict] = []
    samples: list[dict] = []
    errors: list[str] = []
    in_a_row = 0
    next_sample = next_probe = 0.0
    while in_a_row < MAX_ERRORS:
        t = clock() - start
        # a probe first, so the first sample is of a page that has visited the views a probe visits: sampled before them
        # its floor sits under every later one and reads as a rise
        for kind, due, call in (
            ("probe", t >= next_probe < duration, target.probe),
            ("sample", t >= next_sample, target.sample),
        ):
            if not due:
                continue
            if kind == "sample":
                next_sample += every
            else:
                next_probe += interval
            try:
                result = call()
            except Exception as exc:  # noqa: BLE001 - whatever stopped the page is the finding
                errors.append(f"{kind} at {t:.0f} s failed: {type(exc).__name__}: {exc}")
                in_a_row += 1
                continue
            in_a_row = 0
            if kind == "sample":
                samples.append({"t": t, **result})
            else:
                probes.append(probe_record(t, result))
        if t >= duration:
            break
        sleep(
            max(0.0, min(next_sample, next_probe if next_probe < duration else duration, duration) - (clock() - start))
        )
    found = trends(samples)
    return {
        "duration": duration,
        "probes": probes,
        "samples": samples,
        "trends": [{**asdict(t), "upward": t.upward} for t in found],
        "failures": failures(probes, found) + errors,
    }


def finish(report: dict, out: Path) -> int:
    """Write the report, print what failed, and return the exit status."""
    out.write_text(json.dumps(report, indent=2))
    for line in report["failures"]:
        print(f"FAIL {line}", file=sys.stderr)
    print(
        f"{len(report['probes'])} probes, {len(report['samples'])} samples, {len(report['failures'])} failures; {out}",
        file=sys.stderr,
    )
    return 1 if report["failures"] else 0


class Page:
    """The live page in one Chrome tab, and the server process beside it."""

    def __init__(
        self,
        base: str,
        channel: str,
        pinned_pid: int | None,
        what_if: Sequence[str] = pl.WHAT_IF,
        ceilings: Sequence[str] = (),
    ) -> None:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 - the bench group only

        self.base, self.pinned_pid, self.what_if, self.ceilings = base, pinned_pid, what_if, ceilings
        self.port = urllib.parse.urlsplit(base).port or 80
        self.client = pl.Client(base)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(channel=channel, headless=True)
        self.page = self.browser.new_page(viewport={"width": 1600, "height": 1000})
        self.page.add_init_script(pl._PROBE)  # noqa: SLF001 - the page driver beside this script
        self.cdp = self.page.context.new_cdp_session(self.page)
        self.cdp.send("Performance.enable")
        self.page.goto(base, wait_until="domcontentloaded")
        self.page.wait_for_function("window.__sp && window.__sp.firstPaint !== null", timeout=60_000)
        self.home = self.page.evaluate("document.querySelector('#nav button.node.on')?.title ?? null")

    def _metrics(self) -> dict[str, float]:
        return {m["name"]: m["value"] for m in self.cdp.send("Performance.getMetrics")["metrics"]}

    def sample(self) -> dict:
        # what the probe's recorders collected since the last sample is dropped, so the harness does not grow the heap
        self.page.evaluate(
            "(() => { const sp = window.__sp; sp.frames.length = sp.deliveries.length = sp.longTasks.length = 0; })()"
        )
        before = self._metrics()
        self.page.wait_for_timeout(IDLE_WINDOW_S * 1000)
        frames = self.page.evaluate("window.__sp.frames.length")
        long_tasks = self.page.evaluate("window.__sp.longTasks.length")
        after = self._metrics()
        self.cdp.send("HeapProfiler.collectGarbage")
        now = self._metrics()
        sample = {
            "heap": now["JSHeapUsedSize"],
            "nodes": now["Nodes"],
            "listeners": now["JSEventListeners"],
            "frames_per_s": frames / IDLE_WINDOW_S,
            "busy": (after["TaskDuration"] - before["TaskDuration"]) / (after["Timestamp"] - before["Timestamp"]),
            "long_tasks": long_tasks,
        }
        # found again at every sample, so a restart of the server shows as a new pid and not as a dead one
        pid = self.pinned_pid or listening_pid(self.port)
        if pid is not None:
            with contextlib.suppress(OSError):  # it exited between the lookup and the read
                sample.update({"server_pid": pid, **process_stats(pid)})
        print(f"sample {json.dumps(sample)}", file=sys.stderr, flush=True)
        return sample

    def probe(self) -> list[Row]:
        self.page.keyboard.press("Escape")  # a modal an earlier probe failed to close
        rows = [r for r in pl.time_reads(self.client, PROBE_SAMPLES, self.what_if) if r.samples]
        rows.append(pl.time_stream(self.base, PROBE_SAMPLES))
        modal = Row("open a task's modal", "interaction", pl.BUDGET_MS, note="click to the frame after its record")
        self.page.evaluate(pl._CLICK, pl._nav("Kanban"))  # noqa: SLF001
        self.page.wait_for_selector("#cols .card[data-id]", timeout=30_000)
        ids = self.page.eval_on_selector_all("#cols .card[data-id]", "els => els.map(e => e.dataset.id)")
        for task in ids[:PROBE_SAMPLES]:
            opened = self.page.evaluate(pl._OPEN, task)  # noqa: SLF001
            if opened is not None:
                modal.samples.append(opened["ms"])
            self.page.keyboard.press("Escape")
            self.page.wait_for_function(pl._SHOWN_GONE, timeout=10_000)  # noqa: SLF001
        rows.append(modal)
        pl.apply_ceilings(rows, self.ceilings)
        if self.home:
            self.page.evaluate(pl._CLICK, pl._nav(self.home))  # noqa: SLF001
        print(
            f"probe {', '.join(f'{r.name} {r.p95:.1f}' for r in rows if r.over) or 'all under budget'}",
            file=sys.stderr,
            flush=True,
        )
        return rows

    def close(self) -> None:
        self.browser.close()
        self._pw.stop()


def hold(base: str, args: argparse.Namespace, pid: int | None, what_if: Sequence[str]) -> dict:
    """Open the page at `base` in a tab and hold it for the run's duration."""
    page = Page(base, args.channel, pid, what_if, args.ceiling)
    try:
        return run(
            page, parse_duration(args.duration), parse_duration(args.interval), parse_duration(args.sample_every)
        )
    finally:
        page.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "url",
        nargs="?",
        help="the StarPulse page, such as http://127.0.0.1:8766; omit it to hold a seeded server this run starts",
    )
    parser.add_argument("--duration", default="24h", help="how long to hold the page: seconds, 90m or 24h")
    parser.add_argument("--interval", default="10m", help="between budget probes")
    parser.add_argument("--sample-every", default="5m", help="between resource samples")
    parser.add_argument("--channel", default="chrome", help="the Playwright browser channel to drive")
    parser.add_argument("--pid", type=int, help="the server's process; default is the one listening on the URL's port")
    parser.add_argument(
        "--replay-multiple",
        type=float,
        help=f"seeded server only: events replayed as a multiple of the live rate (default {REPLAY_MULTIPLE:g}, "
        "about a day of events through a 4 hour hold)",
    )
    parser.add_argument(
        "--ceiling",
        action="append",
        default=[],
        metavar="ROW=MS",
        help="hold a probe row to MS instead of 50, as page_latency.py does, for a host whose hardware cannot hold "
        "it; the report names each. Repeat for more rows",
    )
    parser.add_argument("--report", type=Path, required=True, help="write the JSON report here")
    args = parser.parse_args(argv)
    if args.url and args.replay_multiple is not None:
        parser.error("--replay-multiple feeds the seeded server; omit the URL to run one")
    if not args.url and args.pid:
        parser.error("--pid names a server this run did not start; omit it for the seeded server")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    if args.url:
        base = args.url.rstrip("/")
        report = hold(base, args, args.pid, pl.WHAT_IF)
        return finish({"url": base, "started": started, "ceilings": args.ceiling, **report}, args.report)
    multiple = REPLAY_MULTIPLE if args.replay_multiple is None else args.replay_multiple
    require_built_page()
    with seeded(multiple) as server:
        report = hold(server.base, args, server.pid, SEEDED_WHAT_IF)
        if gone := server.failure():
            report["failures"].append(gone)
    replay = {"multiple": multiple, "events_per_s": replay_rate(multiple), "events": server.replayed}
    return finish(
        {"url": server.base, "started": started, "ceilings": args.ceiling, "replay": replay, **report}, args.report
    )


if __name__ == "__main__":
    sys.exit(main())
