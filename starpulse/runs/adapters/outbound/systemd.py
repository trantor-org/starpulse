"""The systemd adapter: each allowlisted timer as a workflow with one step, the service it activates, and that service's latest run.

`url` is the allowlist: comma-separated timer units, a bare name read from the system manager and a `user/` prefix from
`systemctl --user`; a name without `.timer` means `<name>.timer`. `Timers.read` reads each timer and its service with
`systemctl show` into the `runs` contract's `Dag` records. `follow` reads the allowlist once, then re-reads only the timer
whose unit systemd reports as changed (a D-Bus `PropertiesChanged` signal, watched through one `gdbus monitor` per
manager, with `Manager.Subscribe` held beside it, which systemd needs before it sends them); a monitor that exits is started again and its timers read again. A `runs:resync` entry naming the instance
reads them all again. `start` is None, since starting a root unit needs a
polkit grant, so a timer has no Run now.
"""

from __future__ import annotations

import os
import queue
import re
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from starpulse.contracts.adapters import RunsSink, RunStatus
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.runs.adapters.outbound.resync import follow_resync

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
        "steps": [
            {
                "name": service,
                "depends": [],
                "status": status,
                "raw": raw,
                "kind": None,
                "precondition": None,
                "lock": None,
                "last": [],
            }
        ],
        "schedule": [],
        "stats": None,
        "rerun": None,
    }


def listing(run: Systemctl, url: str) -> list[dict]:
    """Every timer `url` allowlists as a workflow named for the timer's stem, with its service as the one step."""
    return [_workflow(run, user, unit) for user, unit in units(url)]


def read(url: str) -> list[dict]:
    """Every timer `url` allowlists, as the sweeper's `runs` kind compares them with the projection."""
    return listing(systemctl, url)


class Timers:
    """The allowlist's workflows as last read, and the units whose change means one of them moved."""

    def __init__(self, sink: RunsSink, run: Systemctl, url: str) -> None:
        self.sink, self.run, self.entries = sink, run, units(url)
        self.dags: dict[tuple[bool, str], dict] = {}
        self.owners: dict[tuple[bool, str], tuple[bool, str]] = {}

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
        except OSError as exc:
            self.sink.set_dags(None, str(exc))
        except (ValueError, KeyError) as exc:  # a timestamp or an answer not in the shape `_workflow` reads
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


#: The worker that runs this adapter (`starpulse.runs.model.opt_in`): `serve` supervises it as a child.
WORKER = "systemd"

#: Seconds a monitor that died within `QUICK_EXIT` seconds of starting waits before its restart: a restart backoff, not a listing.
RESTART_BACKOFF = 30.0
QUICK_EXIT = 1.0

#: Seconds the signals of one change are gathered for; a service start signals its states in quick succession.
DEBOUNCE = 0.3

_MONITORED = "org.freedesktop.systemd1"
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


def serve(timers: Timers, events: queue.Queue, stop: StopEvent, debounce: float = DEBOUNCE) -> None:
    """Re-read the timers `events` name, once their signals settle, until `stop` is set. It waits on the queue and on
    nothing else: no listing falls due on a clock."""
    stop.listen(lambda: events.put(None))
    while not stop.is_set():
        first = events.get()
        if first is None:
            return
        changed = {timers.owner(*first)}
        while True:
            try:
                more = events.get(timeout=debounce)
            except queue.Empty:
                break
            if more is not None:
                changed.add(timers.owner(*more))
        changed.discard(None)
        if changed:
            timers.read(changed)


def _bus_path(user: bool) -> str:
    """The socket of the system bus, or of the user's session bus, as `gdbus` finds it."""
    if user:
        address = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus"
    else:
        address = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or "unix:path=/run/dbus/system_bus_socket"
    return address.removeprefix("unix:path=").split(",")[0]


def _call(serial: int, member: str, path: str, interface: str, destination: str) -> bytes:
    """A D-Bus method call with no arguments, as its bytes on the wire (little-endian, version 1)."""
    fields = b""
    for code, sig, value in ((1, b"o", path), (2, b"s", interface), (3, b"s", member), (6, b"s", destination)):
        raw = value.encode()
        fields += b"\0" * (-len(fields) % 8) + bytes([code, 1]) + sig + b"\0" + struct.pack("<I", len(raw)) + raw + b"\0"
    head = b"l\x01\x00\x01" + struct.pack("<III", 0, serial, len(fields))
    return head + fields + b"\0" * (-len(fields) % 8)


@contextmanager
def _subscribed(user: bool) -> Iterator[None]:  # pragma: no mutate block — process boundary
    """Hold `Manager.Subscribe` on one manager's bus for the block. systemd sends a unit's `PropertiesChanged` signals on
    that bus only while some client is subscribed, and `gdbus monitor` never subscribes: the system manager has other
    subscribers (logind), the user manager has none, so its units' signals would never come. systemd drops the
    subscription when this connection closes. Raises `OSError` when the manager refuses or the bus does not answer."""
    with socket.socket(socket.AF_UNIX) as bus:
        bus.settimeout(10)
        bus.connect(_bus_path(user))
        reader = bus.makefile("rb")
        bus.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        if not reader.readline().startswith(b"OK"):
            raise OSError("the bus refused the EXTERNAL authentication")
        bus.sendall(b"BEGIN\r\n")
        bus.sendall(_call(1, "Hello", "/org/freedesktop/DBus", "org.freedesktop.DBus", "org.freedesktop.DBus"))
        bus.sendall(_call(2, "Subscribe", "/org/freedesktop/systemd1", f"{_MONITORED}.Manager", _MONITORED))
        answered = 0
        while answered < 2:
            head = reader.read(16)
            if len(head) < 16:
                raise OSError("the bus closed before answering Subscribe")
            body, _, array = struct.unpack("<III", head[4:])
            reader.read(array + -(16 + array) % 8 + body)
            if head[1] == 3:
                raise OSError("the bus refused Subscribe")
            answered += head[1] == 2
        bus.settimeout(None)
        yield


def monitor(user: bool) -> Iterator[str]:  # pragma: no mutate block — process boundary
    """The lines `gdbus monitor` prints for one manager's bus until it exits, with the manager subscribed meanwhile;
    closing the generator ends the child. `setpriv` sets the parent-death signal and execs, so no Python runs between
    fork and exec."""
    bus = "--session" if user else "--system"
    with (
        _subscribed(user),
        subprocess.Popen(
            ["setpriv", "--pdeathsig", "TERM", "gdbus", "monitor", bus, "--dest", _MONITORED],
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        ) as process,
    ):
        try:
            yield from process.stdout
        finally:
            process.terminate()
    raise OSError(f"gdbus monitor {bus} exited with {process.returncode}")


def follow(  # pragma: no mutate block — thread wiring
    url: str, runs: RunsSink, log: EventLog, stop: StopEvent | None = None
) -> None:
    """Show the timers `url` allowlists on `runs`, moved by the signals of their units. A monitor that exits is started
    again at once and its timers read again, since a signal may have fallen in the gap; a `runs:resync` entry naming the
    instance reads them all again. The threads end when `stop` is set; the server passes none."""
    stop = stop or StopEvent()
    timers = Timers(runs, systemctl, url)
    events: queue.Queue = queue.Queue()

    def relist(user: bool | None = None) -> None:
        for entry_ in timers.entries:
            if user in (None, entry_[0]):
                events.put(entry_)

    def watch(user: bool) -> None:
        while not stop.is_set():
            started = time.monotonic()
            try:
                feed(user, monitor(user), events, lambda u, n: timers.owner(u, n) is not None)
            except OSError:
                pass
            relist(user)
            if time.monotonic() - started < QUICK_EXIT:
                stop.wait(RESTART_BACKOFF)

    for user in {user for user, _ in timers.entries}:
        threading.Thread(target=watch, args=(user,), name=f"systemd-monitor-{user}", daemon=True).start()

    def run() -> None:
        timers.read()
        serve(timers, events, stop)

    threading.Thread(target=run, name="systemd-runs", daemon=True).start()
    follow_resync(log, getattr(runs, "instance", None) or "", relist, stop)
