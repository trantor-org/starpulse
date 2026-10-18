"""The systemd adapter: each allowlisted timer as a workflow with one step, the service it activates, and that service's latest run.

`url` is the allowlist: comma-separated timer units, a bare name read from the system manager and a `user/` prefix from
`systemctl --user`; a name without `.timer` means `<name>.timer`. `Timers.read` reads each timer and its service with
`systemctl show` into the `runs` contract's `Dag` records. `follow` reads the allowlist once, then re-reads only the timer
whose unit systemd reports as changed (a D-Bus `PropertiesChanged` signal, watched through one `gdbus monitor` per
manager) and lists the whole allowlist every `BACKSTOP_INTERVAL` seconds; while a monitor is down it lists every
`RECONCILE_INTERVAL` seconds instead. The event log is not read. `start` is None, since starting a root unit needs a
polkit grant, so a timer has no Run now.
"""

from __future__ import annotations

import ctypes
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime

from starpulse._internal.eventlog.event_log import EventLog
from starpulse.contracts.adapters import RunsSink, RunStatus

#: `systemctl`'s arguments (`--user` first for the user manager) to its standard output; a failing call raises `OSError`.
Systemctl = Callable[[list[str]], str]

#: The `ActiveState`s of a service that has not finished its run: starting, running, reloading or stopping.
_IN_FLIGHT = {"activating", "active", "reloading", "deactivating"}

#: `systemctl` is asked for UTC (`TZ=UTC`), so a timestamp reads `Thu 2026-10-08 20:00:01 UTC`.
_TIMESTAMP = "%a %Y-%m-%d %H:%M:%S UTC"


def entry(raw: str) -> tuple[bool, str]:
    """Whether an allowlist entry names a user timer, and its timer unit (`user/b` is `(True, "b.timer")`)."""
    name = raw.strip()
    user = name.startswith("user/")
    name = name.removeprefix("user/")
    return user, name if name.endswith(".timer") else f"{name}.timer"


def units(url: str) -> list[tuple[bool, str]]:
    """The timers `url` allowlists, in order; an empty allowlist or two timers of one stem (a workflow's name) is refused."""
    out = [entry(raw) for raw in url.split(",") if raw.strip()]
    stems = [unit.removesuffix(".timer") for _, unit in out]
    if not out or len(stems) != len(set(stems)):
        raise ValueError(f"{url!r} is not an allowlist of timers: name at least one, each stem once")
    return out


def _show(run: Systemctl, user: bool, unit: str, *properties: str) -> dict[str, str]:
    """`unit`'s `properties`, by name; a unit systemd does not know is an error, as it is for the page."""
    flags = [arg for name in properties for arg in ("-p", name)]
    out = run([*(["--user"] if user else []), "show", unit, *flags])
    shown = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if shown.get("LoadState") == "not-found":
        raise OSError(f"{unit} is not a {'user' if user else 'system'} unit systemd knows")
    return shown


def _iso(timestamp: str) -> str:
    """A `systemctl` timestamp as ISO 8601 UTC, or empty when the unit has none."""
    if not timestamp:
        return ""
    return datetime.strptime(timestamp, _TIMESTAMP).replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status(active: str, result: str, started: str) -> RunStatus:
    """The status a service's `ActiveState`, `Result` and start time become; a run still going is `running`, a `Result`
    other than `success` is `failed`, and a service that never started is `not_started`."""
    if active in _IN_FLIGHT:
        return "running"
    if result != "success":
        return "failed"
    return "succeeded" if started else "not_started"


def _workflow(run: Systemctl, user: bool, unit: str) -> dict:
    service = _show(run, user, unit, "LoadState", "Unit")["Unit"]
    shown = _show(
        run, user, service, "LoadState", "ActiveState", "Result", "ExecMainStartTimestamp", "ExecMainExitTimestamp"
    )
    started = _iso(shown["ExecMainStartTimestamp"])
    status = _status(shown["ActiveState"], shown["Result"], started)
    raw = f"{shown['ActiveState']}/{shown['Result']}"
    return {
        "name": unit.removesuffix(".timer"),
        "status": status,
        "raw": raw,
        "runId": started,
        "startedAt": started,
        "finishedAt": "" if status == "running" else _iso(shown["ExecMainExitTimestamp"]),
        "steps": [{"name": service, "depends": [], "status": status, "raw": raw, "kind": None}],
    }


def listing(run: Systemctl, url: str) -> list[dict]:
    """Every timer `url` allowlists as a workflow named for the timer's stem, with its service as the one step."""
    return [_workflow(run, user, unit) for user, unit in units(url)]


class Timers:
    """The allowlist's workflows as last read, and the units whose change means one of them moved."""

    def __init__(self, sink: RunsSink, run: Systemctl, url: str) -> None:
        self.sink, self.run, self.entries = sink, run, units(url)
        self.dags: dict[tuple[bool, str], dict] = {}
        self.owners: dict[tuple[bool, str], tuple[bool, str]] = {}
        self.ok = False  # whether the last read succeeded; a failed one is retried at the short interval

    def owner(self, user: bool, unit: str) -> tuple[bool, str] | None:
        """The allowlisted timer `unit` is, or the service it activates; None for any other unit."""
        return self.owners.get((user, unit))

    def read(self, changed: set[tuple[bool, str]] | None = None) -> None:
        """Read the `changed` timers (all of them by default) and hand the allowlist to the page; when it cannot be read
        the last reading stays and the error shows."""
        try:
            for entry_ in changed or self.entries:
                dag = _workflow(self.run, *entry_)
                self.dags[entry_] = dag
                service = dag["steps"][0]["name"]
                self.owners.update({(entry_[0], entry_[1]): entry_, (entry_[0], service): entry_})
            self.sink.set_dags([self.dags[e] for e in self.entries if e in self.dags], None)
            self.ok = True
        except OSError as exc:
            self.ok = False
            self.sink.set_dags(None, str(exc))
        except (ValueError, KeyError) as exc:  # a timestamp or an answer not in the shape `_workflow` reads
            self.ok = False
            self.sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")


def systemctl(args: list[str]) -> str:  # pragma: no mutate block — process boundary
    """Run `systemctl` with `args`, in UTC, and answer what it printed."""
    try:
        done = subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=os.environ | {"TZ": "UTC"},
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"systemctl {' '.join(args)} timed out") from exc
    if done.returncode:
        raise OSError(f"systemctl {' '.join(args)} failed: {done.stderr.strip() or done.returncode}")
    return done.stdout


def start(url: str) -> None:
    """No start capability: starting a system timer's service needs a polkit grant, so a timer has no Run now."""
    return


#: Seconds between two listings of the allowlist while a monitor is down; a timer that fired shows at the next.
RECONCILE_INTERVAL = 30.0

#: Seconds between two listings while every monitor is up: the signals carry the changes, this catches a missed one.
BACKSTOP_INTERVAL = 600.0

#: Seconds the signals of one change are gathered for; a service start signals its states in quick succession.
DEBOUNCE = 0.3

_MONITORED = "org.freedesktop.systemd1"
_PR_SET_PDEATHSIG = 1
_CHANGED = re.compile(r"^/org/freedesktop/systemd1/unit/(\S+): org\.freedesktop\.DBus\.Properties\.PropertiesChanged\b")
_ESCAPED = re.compile(r"_([0-9a-f]{2})")


def changed_unit(line: str) -> str | None:
    """The unit a `gdbus monitor` line reports a property change of (`a_2db_2eservice` is `a-b.service`), else None."""
    match = _CHANGED.match(line)
    return _ESCAPED.sub(lambda m: chr(int(m[1], 16)), match[1]) if match else None


def feed(user: bool, lines: Iterable[str], events: queue.Queue, watched: Callable[[bool, str], bool]) -> None:
    """Queue `(user, unit)` for each line that reports a change of a unit `watched` accepts."""
    for line in lines:
        unit = changed_unit(line)
        if unit is not None and watched(user, unit):
            events.put((user, unit))


def serve(
    timers: Timers,
    events: queue.Queue,
    stop: threading.Event,
    healthy: Callable[[], bool],
    backstop: float = BACKSTOP_INTERVAL,
    fallback: float = RECONCILE_INTERVAL,
    debounce: float = DEBOUNCE,
) -> None:
    """Re-read the timers `events` name, once their signals settle, and every timer when the listing falls due: after
    `backstop` seconds while `healthy()` and the last read succeeded, after `fallback` seconds when not. Nothing runs
    between those."""

    def next_due() -> float:
        return time.monotonic() + (backstop if healthy() and timers.ok else fallback)

    due = next_due()
    while not stop.is_set():
        try:
            first = events.get(timeout=max(0.0, min(due - time.monotonic(), 0.1)))
        except queue.Empty:
            if time.monotonic() >= due:
                timers.read()
                due = next_due()
            continue
        changed = {timers.owner(*first)}
        while True:
            try:
                changed.add(timers.owner(*events.get(timeout=debounce)))
            except queue.Empty:
                break
        changed.discard(None)
        if changed:
            timers.read(changed)
            due = min(due, next_due())


def _die_with_parent() -> None:  # pragma: no mutate block — process boundary
    """Run in the child before exec: have the kernel SIGTERM it when the thread that spawned it ends."""
    ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)


def monitor(user: bool) -> Iterator[str]:  # pragma: no mutate block — process boundary
    """The lines `gdbus monitor` prints for one manager's bus until it exits; closing the generator ends the child."""
    bus = "--session" if user else "--system"
    with subprocess.Popen(
        ["gdbus", "monitor", bus, "--dest", _MONITORED],
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
        preexec_fn=_die_with_parent,
    ) as process:
        try:
            yield from process.stdout
        finally:
            process.terminate()
    raise OSError(f"gdbus monitor {bus} exited with {process.returncode}")


def follow(url: str, runs: RunsSink, log: EventLog) -> None:  # pragma: no mutate block — thread wiring
    """Show the timers `url` allowlists on `runs`, moved by the signals of their units; the event log is not read."""
    timers = Timers(runs, systemctl, url)
    down: set[bool] = set()
    events: queue.Queue = queue.Queue()

    def watch(user: bool) -> None:
        while True:
            try:
                down.discard(user)
                feed(user, monitor(user), events, lambda u, n: timers.owner(u, n) is not None)
            except OSError:
                pass
            down.add(user)
            time.sleep(RECONCILE_INTERVAL)

    for user in {user for user, _ in timers.entries}:
        threading.Thread(target=watch, args=(user,), name=f"systemd-monitor-{user}", daemon=True).start()

    def run() -> None:
        timers.read()
        serve(timers, events, threading.Event(), lambda: not down)

    threading.Thread(target=run, name="systemd-runs", daemon=True).start()
