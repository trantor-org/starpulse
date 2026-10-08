"""The systemd adapter: each allowlisted timer as a workflow with one step, the service it activates, and that service's latest run.

`url` is the allowlist: comma-separated timer units, a bare name read from the system manager and a `user/` prefix from
`systemctl --user`; a name without `.timer` means `<name>.timer`. `listing` reads each timer and its service with
`systemctl show` into the `runs` contract's `Dag` records. `follow` lists every `RECONCILE_INTERVAL` seconds and reads no
event-log entries; `start` is None, since starting a root unit needs a polkit grant, so a timer has no Run now.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from starpulse.contracts.adapters import RunsSink, RunStatus
from starpulse.store.event_log import EventLog

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


def reconcile(sink: RunsSink, run: Systemctl, url: str) -> None:
    """Read the allowlist once and hand it to the page; when it cannot be read the last reading stays and the error shows."""
    try:
        sink.set_dags(listing(run, url), None)
    except OSError as exc:
        sink.set_dags(None, str(exc))
    except (ValueError, KeyError) as exc:  # a timestamp or an answer not in the shape `listing` reads
        sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")


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
    return None


#: Seconds between two listings of the allowlist; a timer that fired since the last one shows at the next.
RECONCILE_INTERVAL = 30.0


def follow(url: str, runs: RunsSink, log: EventLog) -> None:
    """Read the timers `url` allowlists into `runs` every `RECONCILE_INTERVAL` seconds; the event log is not read."""
    units(url)  # an allowlist that is no allowlist fails the instance's start, not its first listing

    def read() -> None:
        while True:
            reconcile(runs, systemctl, url)
            time.sleep(RECONCILE_INTERVAL)

    threading.Thread(target=read, name="systemd-runs", daemon=True).start()
