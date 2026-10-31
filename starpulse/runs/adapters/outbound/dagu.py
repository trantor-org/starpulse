"""The Dagu adapter: each DAG's step graph and latest run, as the `runs` contract's `Dag` records.

`dags` reads one Dagu instance, by URL, into those records. `start` and `follow` are what a runs adapter module
offers the server for one configured instance: its start capability, and the reading of its workflows. The page used to poll Dagu: one listing
plus one request per DAG every few seconds. Dagu's `handler_on` hooks now publish each run's start and end
to `POST /api/machine-events`, so one listing at start and at every reconnect gives each DAG its step graph
and latest run, and the entries on the runs stream after it move them (`DaguRuns`). A listing every 30 s keeps
the page right for a run no entry reported, such as one on a Dagu without the hooks.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import shlex
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

from starpulse.contracts.adapters import LAST_OUTCOMES, RunsSink, RunStatus, StartFailedError
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.event_log.polling import DEFAULT_POLL_INTERVAL
from starpulse.runs.model import run_events

#: Seconds between two listings of a followed Dagu instance.
RECONCILE_INTERVAL = 30.0
#: The worker that runs this adapter (`starpulse.runs.model.opt_in`): `serve` supervises it as a child.
WORKER = "dagu"

#: Each status label Dagu reports (plus `skipped` for a step) and the status it becomes.
#: A run that finished with a failed step is `failed`, one held for an approval is still `running`, and one whose
#: approval was refused is `aborted`; the label itself stays in `raw`.
_STATUS: dict[str, RunStatus] = {
    "not_started": "not_started",
    "queued": "queued",
    "running": "running",
    "waiting": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "partially_succeeded": "failed",
    "aborted": "aborted",
    "rejected": "aborted",
    "skipped": "skipped",
}


def status_of(label: str) -> RunStatus:
    """The status Dagu's `label` becomes; a label Dagu added since is an error, never read as a failure."""
    try:
        return _STATUS[label]
    except KeyError:
        raise ValueError(f"unmapped Dagu status {label!r}") from None


def _reported(label: str) -> dict[str, Any]:
    """A record's `status`, and its `raw` label when the status does not already say it."""
    status = status_of(label)
    return {"status": status} | ({"raw": label} if label != status else {})


def _restated(record: dict, label: str) -> dict:
    """`record` (a DAG or a step) reporting Dagu's `label`, with no `raw` left from the status it had."""
    return {k: v for k, v in record.items() if k != "raw"} | _reported(label)


#: `(method, path, body)` to Dagu's `/api/v1`, answered with the HTTP status and the decoded body; raises
#: `StartFailedError` when Dagu cannot be reached.
Transport = Callable[[str, str, dict | None], tuple[int, dict]]


def connect(base_url: str, timeout: float = 30.0) -> Transport:  # pragma: no mutate block — HTTP boundary
    """A transport to the Dagu instance at `base_url`."""
    base_url = base_url.rstrip("/")

    def send(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{base_url}/api/v1{path}",
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                body = json.loads(raw) if raw else {}
                return response.status, body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as exc:
            return exc.code, {}
        except json.JSONDecodeError as exc:
            raise StartFailedError(f"Dagu returned malformed JSON: {exc}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise StartFailedError(f"Dagu unreachable: {exc}") from exc

    return send


def _launch(transport: Transport, dag: str, body: dict) -> str:
    """Ask Dagu to start `dag` with the request `body` and return the run's id."""
    status, answer = transport("POST", f"/dags/{dag}/start", body)
    if status != 200 or not answer.get("dagRunId"):
        raise StartFailedError(f"Dagu refused the start (HTTP {status})")
    return answer["dagRunId"]


def starter(transport: Transport) -> Callable[[str], str]:
    """The adapter's start capability: asks Dagu to start a DAG and returns the run's id.

    Dagu's `/start` hands a run to a worker without consulting `maxActiveRuns` (only its queue enforces it) or the
    body's `singleton`, so a burst of starts runs them all at once. The start is refused with `StartFailedError`
    while the DAG's running and queued runs have reached that limit; the caller drops it, as it does any refusal.
    The check and the start run under one lock, so starts racing in this process (two Run nows)
    cannot both find room.
    """
    lock = threading.Lock()

    def start(dag: str) -> str:
        with lock:
            if (limit := _active_run_limit_reached(transport, dag)) is not None:
                raise StartFailedError(f"{dag} is at its active run limit ({limit})")
            return _launch(transport, dag, {})

    return start


#: What Dagu reads as one `NAME=value` word, with no quoting, substitution or splitting to get wrong.
_PARAM_NAME = re.compile(r"[A-Za-z_]\w*")
_PARAM_VALUE = re.compile(r"[\w.@:/+,-]*")


def rerunner(transport: Transport) -> Callable[[str, Mapping[str, str]], str]:
    """The adapter's rerun capability: asks Dagu to start a DAG with `params` and returns the run's id.

    A name or value that is not a plain word is refused before Dagu is asked, as Dagu would read a space as a second
    parameter and a backtick as a command to run.
    """

    def rerun(dag: str, params: Mapping[str, str]) -> str:
        for name, value in params.items():
            if not (_PARAM_NAME.fullmatch(name) and _PARAM_VALUE.fullmatch(value)):
                raise StartFailedError(f"parameter {name} is not a plain NAME=value word Dagu can be given")
        return _launch(transport, dag, {"params": " ".join(f"{name}={value}" for name, value in params.items())})

    return rerun


#: How long a single read of Dagu may take, and a scan of a window of runs: Dagu answers the latter in seconds, each page
#: costing a scan of the whole window, and a client that gives up first leaves Dagu scanning for nobody.
_READ_TIMEOUT = 5
_SCAN_TIMEOUT = 60


def _get(url: str, timeout: float = _READ_TIMEOUT) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def _precondition(step: dict) -> str | None:
    """What a step's `preconditions` demand, as `condition == expected` joined by `; `; None when it declares none."""
    words = [
        f"{p['condition']} == {p['expected']}" if p.get("expected") else p["condition"]
        for p in step.get("preconditions") or []
        if p.get("condition")
    ]
    return "; ".join(words) or None


def _outcomes(base_url: str, name: str) -> dict[str, list[RunStatus]]:
    """Each step's statuses in the DAG's runs that are over, newest first, at most `LAST_OUTCOMES`; none when Dagu cannot list them."""
    try:
        runs = _get(f"{base_url}/api/v1/dags/{name}/dag-runs").get("dagRuns", [])
    except OSError:
        return {}
    out: dict[str, list[RunStatus]] = {}
    for run in runs:
        if status_of(run["statusLabel"]) in _OPEN:
            continue
        for node in run.get("nodes", []):
            status, kept = (status_of(node["statusLabel"]), out.setdefault(node["step"]["name"], []))
            if status not in _OPEN | {"not_started"} and len(kept) < LAST_OUTCOMES:
                kept.append(status)
    return out


def _steps(base_url: str, name: str) -> tuple[str, list[dict]]:
    """The queue a DAG declares, and its steps: each with the steps it waits on, its status in the latest run, its declared kind and precondition, and its last outcomes.

    Dagu declares no step lock, so `lock` is None.
    """
    detail = _get(f"{base_url}/api/v1/dags/{name}")
    ran = {n["step"]["name"]: n["statusLabel"] for n in (detail.get("latestDAGRun") or {}).get("nodes", [])}
    last = _outcomes(base_url, name)
    return detail["dag"].get("queue", ""), [
        {
            "name": s["name"],
            "depends": s.get("depends", []),
            **_reported(ran.get(s["name"], "not_started")),
            "kind": _kind(s),
            "precondition": _precondition(s),
            "lock": None,
            "last": last.get(s["name"], []),
        }
        for s in detail["dag"].get("steps", [])
    ]


def declared_params(base_url: str, name: str) -> list[str]:
    """The names of the parameters DAG `name` declares: `params` reports each defaulted one as `NAME=default`, and a DAG with a schema lists all of them in `paramDefs`."""
    dag = _get(f"{base_url}/api/v1/dags/{urllib.parse.quote(name)}")["dag"]
    words = [word.partition("=")[0] for word in dag.get("params", []) if "=" in word]
    return words + [d["name"] for d in dag.get("paramDefs", []) if d["name"] not in words]


def _kind(step: dict) -> str | None:
    """The phase kind a rendered step declares as its description (`kind: agent`), else None."""
    description = step.get("description", "")  # pragma: no mutate: a default lacking the prefix is equivalent
    if not description.startswith("kind: "):
        return None
    return description.removeprefix("kind: ").strip() or None


#: Dagu's numeric run statuses, as `/dag-runs?status=` filters by them.
_RUNNING, _QUEUED = 1, 5
#: How far back a start looks for the DAG's active runs. It reads on every start, and Dagu answers a week's
#: window about four times slower than a day's; a run older than this is not seen, so its DAG starts again.
_START_LOOKBACK = 86400


def _active_run_limit_reached(transport: Transport, dag: str) -> int | None:
    """The DAG's `maxActiveRuns` when its running and queued runs have reached it, else None.

    A limit or a count Dagu does not answer reads as not reached: the start goes ahead rather than being held back
    on a guess, and a DAG with no positive limit is never held back.
    """
    name = urllib.parse.quote(dag)
    status, detail = transport("GET", f"/dags/{name}", None)
    limit = detail.get("dag", {}).get("maxActiveRuns")
    if status != 200 or not isinstance(limit, int) or limit < 1:
        return None
    since = int(time.time()) - _START_LOOKBACK
    active = 0
    for state in (_RUNNING, _QUEUED):
        status, listed = transport("GET", f"/dag-runs?name={name}&status={state}&fromDate={since}", None)
        if status != 200:
            return None
        active += len(listed.get("dagRuns", []))
    return limit if active >= limit else None


def pools(base_url: str) -> list[dict]:
    """Every Dagu queue as a pool: its cap, and the runs it holds and has waiting; none when Dagu reports no queues."""
    try:
        queues = _get(f"{base_url}/api/v1/queues").get("queues", [])
    except OSError:
        return []
    return [
        {"name": q["name"], "cap": q["maxConcurrency"], "running": q["runningCount"], "queued": q["queuedCount"]}
        for q in queues
    ]


def _in_flight(base_url: str) -> dict[str, list[dict]]:
    """Each DAG's running runs, longest-running first, then its queued ones, oldest first; none when Dagu cannot list them.

    The queues hold them: `/queues` carries each queue's running runs, and `/queues/<name>/items` the queued ones of a
    queue that has any. Listing runs by status instead makes Dagu scan every run of the window, which a poll of seconds
    kept it doing around the clock.
    """
    running: list[dict] = []
    queued: list[dict] = []
    try:
        for held in _get(f"{base_url}/api/v1/queues").get("queues", []):
            running += held.get("running", [])
            if held.get("queuedCount"):
                queued += _get(f"{base_url}/api/v1/queues/{urllib.parse.quote(held['name'])}/items").get("items", [])
    except OSError:
        return {}
    out: dict[str, list[dict]] = {}
    for runs, begun in ((running, "startedAt"), (queued, "queuedAt")):
        for run in sorted(runs, key=lambda r: r.get(begun, "")):
            out.setdefault(run["name"], []).append(run)
    return out


def _active(base_url: str, run: dict, steps: list[dict]) -> dict | None:
    """One running or queued run with its steps and the step it entered last; None once Dagu no longer has it."""
    try:
        nodes = _get(f"{base_url}/api/v1/dag-runs/{run['name']}/{run['dagRunId']}")["dagRunDetails"].get("nodes", [])
    except OSError:  # it finished and was removed between the listing and this read
        return None
    entered = max(
        (n for n in nodes if status_of(n["statusLabel"]) == "running"), key=lambda n: n.get("startedAt", ""), default={}
    )
    return {
        "runId": run["dagRunId"],
        **_reported(run["statusLabel"]),
        "startedAt": run.get("startedAt") or run.get("queuedAt") or "",
        "step": entered.get("step", {}).get("name", ""),
        "stepStartedAt": entered.get("startedAt", ""),
        "steps": {s["name"]: "not_started" for s in steps}
        | {n["step"]["name"]: status_of(n["statusLabel"]) for n in nodes},
    }


#: How far back a tied DAG's recent runs reach, and how many `/dag-runs` returns per page.
_RECENT_LOOKBACK = 86400
_PAGE = 100
#: The statuses of a run that is not over; the steps of any other are final once read.
_OPEN = {"running", "queued"}


def _params(text: str) -> dict[str, str]:
    """The `KEY=value` words of a run's parameters as Dagu prints them (a value with spaces is quoted); positional words are dropped."""
    try:
        words = shlex.split(text)
    except ValueError:  # an unbalanced quote: split on spaces rather than lose every parameter
        words = text.split()
    pairs = (word.partition("=") for word in words)
    return {key: value for key, equals, value in pairs if equals and key}


_TASK_RUN = re.compile(r"dag-run-task-(\d+)-")


def _task_of(run_id: str) -> str | None:
    """The Board task a `dag-run-task-<N>-<ts>` run id names, or None for any other run."""
    match = _TASK_RUN.match(run_id)
    return f"TASK-{match.group(1)}" if match else None


def _recent_run(base_url: str, run: dict) -> dict:
    """One listed run as a `RecentRun`, its steps read from its detail (none when Dagu no longer has it)."""
    try:
        nodes = _get(f"{base_url}/api/v1/dag-runs/{run['name']}/{run['dagRunId']}")["dagRunDetails"].get("nodes", [])
    except OSError:
        nodes = []
    return {
        "runId": run["dagRunId"],
        "task": _task_of(run["dagRunId"]),
        "url": f"{base_url}/dag-runs/{urllib.parse.quote(run['name'])}/{urllib.parse.quote(run['dagRunId'])}",
        **_reported(run["statusLabel"]),
        "startedAt": run.get("startedAt") or run.get("queuedAt") or "",
        "finishedAt": run.get("finishedAt", ""),
        "params": _params(run.get("params", "")),
        "steps": {n["step"]["name"]: status_of(n["statusLabel"]) for n in nodes},
    }


def _listed(base_url: str, name: str, since: int) -> list[dict]:
    """The runs of DAG `name` that began at or after epoch second `since`, newest first, read page by page; an `OSError` if Dagu cannot list them."""
    cursor, runs = "", []
    while True:
        more = f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""
        page = _get(
            f"{base_url}/api/v1/dag-runs?name={urllib.parse.quote(name)}&perPage={_PAGE}&fromDate={since}{more}",
            _SCAN_TIMEOUT,
        )
        runs += page.get("dagRuns", [])
        if not (cursor := page.get("nextCursor") or ""):
            return runs


def _began(run: dict) -> float:
    """The epoch second a listed run began, or was queued; 0 when Dagu gives no readable time."""
    return _epoch(run.get("startedAt") or run.get("queuedAt") or "") or 0.0


def recent_runs(base_url: str, name: str, finished: dict | None = None) -> list[dict]:
    """The last day's runs of DAG `name` as `RecentRun` records, in the order Dagu lists them (newest first).

    A run that is over keeps the steps it was read with in `finished`, so only runs in flight cost a detail read; the
    entries of `name` that Dagu no longer lists leave it. `finished` also keeps the listing under `(name, "")`: a read
    lists only the runs since the last, or since the oldest run then still open when that is earlier, so a read costs a
    short window rather than a day's. A listing Dagu cannot give serves what was kept, none when nothing is.
    """
    cache = {} if finished is None else finished
    now = time.time()
    window = now - _RECENT_LOOKBACK
    seen = cache.get((name, ""), {"wall": None, "runs": []})
    runs = seen["runs"]
    open_since = [_began(run) for run in runs if status_of(run["statusLabel"]) in _OPEN]
    since = window if seen["wall"] is None else max(window, min([seen["wall"], *open_since]) - 60)
    try:
        listed = _listed(base_url, name, int(since))
    except OSError:
        pass
    else:
        relisted = {run["dagRunId"] for run in listed}
        kept = [run for run in runs if run["dagRunId"] not in relisted and _began(run) >= window]
        runs = listed + kept
        cache[(name, "")] = {"wall": now, "runs": runs}
    out = []
    for run in runs:
        key = (name, run["dagRunId"])
        out.append(cache[key] if key in cache else _recent_run(base_url, run))
        if out[-1]["status"] not in _OPEN:
            cache[key] = out[-1]
    live = {(name, run["dagRunId"]) for run in runs} | {(name, "")}
    for key in [k for k in cache if k[0] == name and k not in live]:
        del cache[key]
    return out


#: The window of a DAG's run statistics, how long they are kept before the DAG's runs are read again, and how many DAGs
#: are read at once. Dagu answers a DAG's week of runs slowly (a busy DAG's takes a minute and more, each page costing a
#: scan of the window) yet no slower for several at once, so `refresh_stats` reads the DAGs in parallel, off the
#: listing: a listing serves what is kept and shows a DAG not read yet with no statistics.
STATS_WINDOW = 7 * 86400
STATS_TTL = 300.0
STATS_WORKERS = 8

#: The labels a DAG declares its rerun safety with: `rerun=safe`, `rerun-key=<key>` (its effects are keyed, so a rerun for
#: the same key repeats none), or `rerun-repeats=<why>` with the `rerun-step=<step>` that repeats. Dagu allows only
#: `a-z A-Z 0-9 - _ . /` in a label value, so a reason is written with hyphens.
RERUN_LABELS = ("rerun", "rerun-key", "rerun-repeats", "rerun-step")


#: The label a DAG declares its domain with: `domain=<name>`. Dagu allows only `a-z A-Z 0-9 - _ . /` in a label value, so
#: the page's name spells `-and-` as ` & ` and every other `-` as a space (`Delivery-and-CI` is "Delivery & CI").
DOMAIN_LABEL = "domain"


def domain_name(slug: str) -> str:
    """The domain name the page draws for a `domain=` label's `slug`."""
    return slug.replace("-and-", " & ").replace("-", " ")


def domains(base_url: str) -> dict[str, tuple[str, ...]]:
    """The DAGs of a Dagu instance by the domain their `domain=` label names, name-sorted; a DAG with none is left out.

    Domains come in name order, workflows name-sorted within each.
    """
    grouped: dict[str, list[str]] = {}
    for entry in _get(f"{base_url}/api/v1/dags?perPage=200").get("dags", []):
        labels = entry.get("dag", {}).get("labels") or []
        for label_name, sep, value in (label.partition("=") for label in labels):
            if sep and label_name == DOMAIN_LABEL:
                grouped.setdefault(domain_name(value), []).append(entry["fileName"])
    return {domain: tuple(sorted(names)) for domain, names in sorted(grouped.items())}


def _rerun_of(labels: list[str]) -> dict | None:
    """The rerun safety the DAG's `labels` declare, or None when they declare none (a `rerun-step` alone declares none)."""
    declared = {
        name: value for name, sep, value in (label.partition("=") for label in labels) if sep and name in RERUN_LABELS
    }
    key, repeats = declared.get("rerun-key"), declared.get("rerun-repeats")
    if not (key or repeats or declared.get("rerun") == "safe"):
        return None
    return {"key": key, "repeats": repeats, "step": declared.get("rerun-step") if repeats else None}


#: Where the host's cgroups for systemd services are, and the units that run Dagu: its scheduler, its workers and the
#: units beside them (`dagu*.service`).
CGROUP_ROOT = Path("/sys/fs/cgroup/system.slice")
CPU_UNITS = ("dagu*.service",)


class CpuSampler:
    """The share of all the host's cores the Dagu units used between this call and the one before it.

    Each unit's cgroup counts its own and its children's CPU time since it began, so the units are summed (the scheduler,
    every worker, and what their jobs spawn). A unit that began since the last call counts what it has used, one that
    ended counts nothing, and one whose counter fell was restarted and counts what it has used since. The first call,
    and one that finds no unit, has no reading: None.
    """

    def __init__(
        self,
        root: Path = CGROUP_ROOT,
        units: tuple[str, ...] = CPU_UNITS,
        *,
        cores: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = root
        self._units = units
        self._cores = cores or os.cpu_count() or 1
        self._clock = clock
        self._last: tuple[dict[str, int], float] | None = None

    def _usage(self) -> dict[str, int]:
        used: dict[str, int] = {}
        for unit in (path for pattern in self._units for path in self._root.glob(pattern)):
            try:
                used[unit.name] = int((unit / "cpu.stat").read_text().split()[1])
            except OSError, ValueError, IndexError:  # the unit ended while it was read
                continue
        return used

    def __call__(self) -> dict | None:
        used, now = self._usage(), self._clock()
        last, self._last = self._last, (used, now)
        if last is None or not used or now <= last[1]:
            return None
        before, then = last
        spent = sum(cur - before.get(unit, 0) if cur >= before.get(unit, 0) else cur for unit, cur in used.items())
        share = spent / 1e6 / ((now - then) * self._cores)
        return {"share": round(min(share, 1.0), 3), "cores": self._cores}


def _epoch(text: str) -> float | None:
    """The epoch second of a Dagu timestamp, None for an empty or unreadable one."""
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _read_stats(base_url: str, name: str, kept: dict | None, at: float, wall: float) -> dict:
    """The runs of DAG `name` in the window, merged into those `kept` from the last read.

    The runs listed are those since the last read, or since the oldest run then still open when that is earlier
    (it may have ended), so a refresh costs a short listing rather than a week's.
    """
    window = wall - STATS_WINDOW
    runs = dict(kept["runs"]) if kept else {}
    open_since = [start for start, end, _ in runs.values() if end is None]
    since = window if kept is None else max(window, min([kept["wall"], *open_since]) - 60)
    for run in _listed(base_url, name, int(since)):
        start = _epoch(run.get("startedAt") or run.get("queuedAt") or "")
        status = status_of(run["statusLabel"])
        if start is not None:
            runs[run["dagRunId"]] = (start, None if status in _OPEN else _epoch(run.get("finishedAt", "")), status)
    return {"read": at, "wall": wall, "runs": {k: v for k, v in runs.items() if v[0] >= window}}


def _stats_of(runs: Collection[tuple[float, float | None, RunStatus]]) -> dict[str, Any]:
    """The count of runs in the window, their hours, and the median and 95th-percentile duration and failure share of those that are over (None when none is)."""
    lasted = sorted(max(0.0, end - start) for start, end, _ in runs if end is not None)
    failed = sum(1 for _, end, status in runs if end is not None and status == "failed")
    return {
        "runs": len(runs),
        "hours": round(sum(lasted) / 3600, 2),
        "medianSeconds": statistics.median(lasted) if lasted else None,
        "p95Seconds": lasted[math.ceil(0.95 * len(lasted)) - 1] if lasted else None,
        "failureShare": failed / len(lasted) if lasted else None,
    }


#: How long a DAG's step graph is kept once read. Dagu's listing carries no marker of a DAG file's change, so a
#: graph edited under an unchanged latest run shows up this late.
GRAPH_TTL = 600.0


def _graph(base_url: str, name: str, run: dict, graphs: dict, now: float) -> tuple[str, list[dict]]:
    """The DAG's pool and steps: kept in `graphs` while its latest run is unchanged and over and the TTL has not passed.

    A run still open is read each time, as its steps move while its status stays `running`; a read that fails is not kept.
    """
    marker = (run.get("dagRunId", ""), run.get("statusLabel", ""), run.get("finishedAt", ""))
    if (kept := graphs.get(name)) and kept[0] == marker and marker[1] not in _OPEN and now - kept[1] < GRAPH_TTL:
        return kept[2]
    graph = _steps(base_url, name)
    graphs[name] = (marker, now, graph)
    return graph


def refresh_stats(
    base_url: str, stats: dict, clock: Callable[[], float] = time.monotonic, tried: dict | None = None
) -> None:
    """Read the run statistics of the DAGs Dagu lists with a latest run and whose kept read is older than `STATS_TTL`.

    The DAGs are read `STATS_WORKERS` at a time, the unread ones first and then the stalest, and every one is read
    however long that takes. A read Dagu fails is tried again once `STATS_TTL` has passed since it was tried (`tried`
    keeps when, between refreshes): a read that fails at once again keeps Dagu scanning the whole window for nobody.
    The DAGs Dagu no longer lists leave `stats`.
    """
    asked = {} if tried is None else tried
    listed = _get(f"{base_url}/api/v1/dags?perPage=200").get("dags", [])
    for gone in stats.keys() - {d["fileName"] for d in listed}:
        del stats[gone]
    ran = [d["fileName"] for d in listed if d.get("latestDAGRun")]
    stale = [n for n in ran if n not in stats or clock() - stats[n]["read"] >= STATS_TTL]
    stale = [n for n in stale if clock() - asked.get(n, -math.inf) >= STATS_TTL]
    stale.sort(key=lambda n: stats[n]["read"] if n in stats else -math.inf)

    def read(name: str) -> None:
        asked[name] = clock()
        try:
            stats[name] = _read_stats(base_url, name, stats.get(name), clock(), time.time())
        except OSError:
            pass

    unread: queue.SimpleQueue[str] = queue.SimpleQueue()
    for name in stale:
        unread.put(name)

    def drain() -> None:
        while True:
            try:
                read(unread.get_nowait())
            except queue.Empty:
                return

    # daemon threads, not an executor: an executor's threads are joined at exit and first finish every queued read, which
    # held a stopping worker for as long as a cold pass takes (minutes)
    workers = [threading.Thread(target=drain, name="stats-read", daemon=True) for _ in range(STATS_WORKERS)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()


def dags(
    base_url: str,
    only: Collection[str] | None = None,
    recent: Collection[str] = (),
    finished: dict | None = None,
    graphs: dict | None = None,
    clock: Callable[[], float] = time.monotonic,
    stats: dict | None = None,
) -> list[dict]:
    """Every DAG on a Dagu instance, or just those in `only`, with its latest run, schedule, step graph, pool and run statistics.

    A full listing also reads each DAG's active runs; the listing of `only` leaves them out, as it serves a step read
    after one run entry. A DAG whose detail cannot be read is listed without steps or pool rather than failing the listing.
    `graphs` keeps each DAG's graph between listings (see `_graph`); a full listing drops the DAGs it no longer shows.
    `stats` keeps each DAG's runs of the last `STATS_WINDOW` between listings, as `refresh_stats` reads them; a listing
    serves what is kept. A DAG with no run, or whose statistics have not been read yet, has `stats` None, never zeros.
    """
    graphs = {} if graphs is None else graphs
    stats = {} if stats is None else stats
    in_flight = _in_flight(base_url) if only is None else {}
    listed = _get(f"{base_url}/api/v1/dags?perPage=200").get("dags", [])
    if only is None:
        for gone in graphs.keys() - {d["fileName"] for d in listed}:
            del graphs[gone]
    out = []
    for d in listed:
        if only is not None and d["fileName"] not in only:
            continue
        run = d.get("latestDAGRun") or {}
        kept = stats.get(d["fileName"])  # another thread may be refreshing: read once
        # a DAG whose runs name a task keeps them too, so the task's card links them though no Board event ties it
        keeps_recent = d["fileName"] in recent or _task_of(run.get("dagRunId", "")) is not None
        try:
            pool, steps = _graph(base_url, d["fileName"], run, graphs, clock())
        except OSError:
            pool, steps = "", []
        out.append(
            {
                "name": d["fileName"],
                **_reported(run.get("statusLabel") or "not_started"),
                "runId": run.get("dagRunId", ""),
                "startedAt": run.get("startedAt") or run.get("queuedAt") or "",
                "finishedAt": run.get("finishedAt", ""),
                "steps": steps,
                "schedule": [s["expression"] for s in d.get("dag", {}).get("schedule") or []],
                "stats": _stats_of(kept["runs"].values()) if kept else None,
                "rerun": _rerun_of(d.get("dag", {}).get("labels") or []),
                "active": [a for r in in_flight.get(d["fileName"], []) if (a := _active(base_url, r, steps))],
                "pool": pool,
                **({"recent": recent_runs(base_url, d["fileName"], finished)} if keeps_recent else {}),
            }
        )
    return out


@dataclass(frozen=True)
class _Run:
    """One decoded run entry of the runs stream."""

    event: str
    dag: str
    run_id: str
    status: str
    at: float
    step: str


def _decode(fields: dict) -> _Run | None:
    """The run (or, with `step`, the step of a run) an entry reports, or None for one the contract does not allow."""
    try:
        run = _Run(
            fields["event"],
            fields["workflow"],
            fields["run_id"],
            fields["status"],
            float(fields["time"]),
            fields.get("step") or "",
        )
    except KeyError, ValueError:
        return None
    well_formed = run.event in run_events.EVENTS and run.status in get_args(RunStatus)
    return run if well_formed else None


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stepped(dag: dict, run: _Run) -> dict | None:
    """`dag` with the step `run` reports moved in the run it names, or None when that run is neither active nor the latest.

    A run in flight keeps its own step and step statuses; the steps the DAG itself shows are the latest run's.
    """
    mine = next((a for a in dag.get("active", []) if a["runId"] == run.run_id), None)
    latest = run.run_id == dag["runId"]
    if mine is None and not latest:
        return None
    moved = dag
    if mine is not None:
        if run.status == "running":
            step, since = run.step, _iso(run.at)
        elif mine["step"] == run.step:
            step, since = "", ""
        else:
            step, since = mine["step"], mine["stepStartedAt"]
        entry = {**mine, "step": step, "stepStartedAt": since, "steps": mine["steps"] | {run.step: run.status}}
        moved = {**moved, "active": [entry if a["runId"] == run.run_id else a for a in dag["active"]]}
    if latest:
        moved = {**moved, "steps": [_restated(s, run.status) if s["name"] == run.step else s for s in dag["steps"]]}
    return moved


def _patched(recent: list[dict], run: _Run) -> list[dict]:
    """`recent` with the run an entry reports moved: a step's status, or the run's own status and end."""
    out = []
    for entry in recent:
        if entry["runId"] == run.run_id:
            if run.step:
                entry = {**entry, "steps": entry["steps"] | {run.step: run.status}}
            elif run.event != "StepStarted":
                entry = _restated(entry, run.status) | {"finishedAt": _iso(run.at)}
        out.append(entry)
    return out


def _begun(recent: list[dict], run: _Run) -> list[dict]:
    """`recent` holding the run a start entry reports, with no parameters when Dagu has not listed it yet."""
    if any(entry["runId"] == run.run_id for entry in recent):
        return recent
    begun = {
        "runId": run.run_id,
        "task": _task_of(run.run_id),
        "url": "",
        "status": "running",
        "startedAt": _iso(run.at),
        "finishedAt": "",
        "params": {},
        "steps": {},
    }
    return [begun, *recent]


class DaguRuns:
    """The DAGs as the page draws them, from `fetch` (one Dagu listing, of the named DAGs or all) and then run entries.

    `pools` reads the instance's concurrency pools alongside each full listing. `tied` names the workflows whose
    recent runs (`Dag.recent`) are kept: `fetch` reads them with each listing, and an entry moves them in step with
    the run it reports, a start reading the run once more for the parameters it began with. An ingested entry
    carries its producer as `instance`: it is applied when that is this reader's `instance`, dropped when another's.

    Entries and reconnects arrive on the consumer thread and the periodic reconcile runs on its own, so the
    DAGs are held under a lock; the sink holds the page-facing state and its own.
    """

    def __init__(
        self,
        sink: RunsSink,
        fetch: Callable[[Collection[str] | None], list],
        pools: Callable[[], list[dict]] = list,
        *,
        cpu: Callable[[], dict | None] = lambda: None,
        tied: Callable[[], Collection[str]] = frozenset,
        instance: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._instance = instance
        self._sink = sink
        self._fetch = fetch
        self._pools = pools
        self._cpu = cpu
        self._tied = tied
        self._clock = clock
        self._lock = threading.RLock()
        self._dags: dict[str, dict[str, Any]] = {}
        #: When the entry that last moved each DAG was stamped; a listing that began before it is the older state.
        self._streamed: dict[str, float] = {}
        #: When the last listing began; an entry stamped before it is already in that listing.
        self._listed_at = 0.0

    def reconcile(self) -> None:
        """Read Dagu once and merge it; when it is unreachable the DAGs last read stay and the error shows.

        A DAG an entry moved after this listing began keeps the entry's state, which is newer than the listing's.
        """
        listed_at = self._clock()
        try:
            listed = self._fetch(None)
            pools = self._pools()
            cpu = self._cpu()
        except OSError as exc:
            self._sink.set_dags(None, str(exc))
            return
        except (ValueError, KeyError, TypeError) as exc:  # an answer that is not JSON or not the shape `dags` reads
            self._sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")
            return
        with self._lock:
            if listed_at < self._listed_at:
                return  # a listing that began later was merged while this one was read
            self._listed_at = listed_at
            self._dags = {
                dag["name"]: dag if self._streamed.get(dag["name"], -math.inf) < listed_at else self._dags[dag["name"]]
                for dag in listed
            }
            self._sink.set_dags(list(self._dags.values()), None, pools, cpu=cpu)

    def _listed(self, name: str) -> dict | None:
        """`name` as Dagu lists it now, or None when Dagu lacks it or cannot be read; the next reconcile corrects either."""
        try:
            return next((dag for dag in self._fetch({name}) if dag["name"] == name), None)
        except OSError, ValueError, KeyError, TypeError:
            return None

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Move one DAG by a run entry; a malformed entry, one the last listing already holds, or one for a workflow Dagu lacks is dropped."""
        with self._lock:
            self._apply(fields)

    def _apply(self, fields: dict) -> None:
        run = _decode(fields)
        producer = fields.get("instance")
        foreign = (
            producer and producer != self._instance
        )  # an ingested entry is its producer's, applied only by that instance
        if run is None or foreign or run.at < self._listed_at:
            return
        dag = self._dags.get(run.dag)
        if dag is None:  # a DAG file added since the listing
            if not self._adopt_unlisted(run):
                return
            dag = self._dags[run.dag]
        tied = run.dag in self._tied()
        if (move := self._move(dag, run, tied)) is None:
            return
        moved, fresh = move
        if tied:
            recent = fresh if fresh is not None else _patched(dag.get("recent", []), run)
            moved = {**moved, "recent": _begun(recent, run) if run.event == "StepStarted" and not run.step else recent}
        self._dags[run.dag] = moved
        self._streamed[run.dag] = run.at
        self._sink.set_dags(list(self._dags.values()), None)

    def _adopt_unlisted(self, run: _Run) -> bool:
        """Read the DAG of an entry the last listing lacks; False when Dagu lacks it too or the listing read holds the entry."""
        listed_at = self._clock()
        dag = self._listed(run.dag)
        if dag is None:
            return False
        self._dags[run.dag] = dag
        if run.at < listed_at:  # the entry is already in what Dagu just listed
            self._sink.set_dags(list(self._dags.values()), None)
            return False
        return True

    def _move(self, dag: dict, run: _Run, tied: bool) -> tuple[dict, list | None] | None:
        """The DAG after `run`, with the recent runs Dagu listed when the entry needed one; None when the entry moves nothing."""
        others = [a for a in dag.get("active", []) if a["runId"] != run.run_id]
        known = any(r["runId"] == run.run_id for r in dag.get("recent", []))
        current = "step" if run.step else "drawn" if run.run_id == dag["runId"] else "other"
        move = _MOVES.get((current, run.event)) or _MOVES[(current, "")]
        return move(self, dag, run, others, tied, known)


def _step_move(
    reader: DaguRuns, dag: dict, run: _Run, others: list, tied: bool, known: bool
) -> tuple[dict, None] | None:
    moved = _stepped(dag, run) or (dag if tied and known else None)
    return None if moved is None else (moved, None)


def _begin_move(
    reader: DaguRuns, dag: dict, run: _Run, others: list, tied: bool, known: bool
) -> tuple[dict, list | None]:
    fresh = None
    if tied and (listed := reader._listed(run.dag)):
        fresh = listed.get("recent")
    begun = {
        "runId": run.run_id,
        "status": "running",
        "startedAt": _iso(run.at),
        "step": "",
        "stepStartedAt": "",
        "steps": {step["name"]: "not_started" for step in dag["steps"]},
    }
    moved = _restated(dag, "running") | {
        "runId": run.run_id,
        "startedAt": _iso(run.at),
        "finishedAt": "",
        "steps": [_restated(step, "not_started") for step in dag["steps"]],
        "active": [*others, begun],
    }
    return moved, fresh


def _finish_move(
    reader: DaguRuns, dag: dict, run: _Run, others: list, tied: bool, known: bool
) -> tuple[dict, list | None]:
    # Dagu is still inside the run's exit handler, so only its steps are final: read them now.
    listed = reader._listed(run.dag)
    fresh = listed.get("recent") if listed else None
    moved = _restated(dag, run.status) | {
        "finishedAt": _iso(run.at),
        "steps": listed["steps"] if listed else dag["steps"],
        "active": others,
    }
    return moved, fresh


def _other_move(
    reader: DaguRuns, dag: dict, run: _Run, others: list, tied: bool, known: bool
) -> tuple[dict, None] | None:
    if len(others) < len(dag.get("active", [])):
        return {**dag, "active": others}, None  # the end of a run no longer the one drawn, still listed as active
    if tied and known:
        return (dag, None)  # no longer the one drawn, and not active, but a run the ledger still holds
    return None  # the end of a run that is no longer the one drawn


#: How an entry moves its DAG, keyed by its run's place in the DAG as drawn (`step`, `drawn` or `other`) and its event.
_MOVES = {
    ("step", ""): _step_move,
    ("drawn", "StepStarted"): _begin_move,
    ("drawn", ""): _finish_move,
    ("other", "StepStarted"): _begin_move,
    ("other", ""): _other_move,
}


def start(url: str) -> Callable[[str], str]:
    """The start capability of the Dagu instance at `url`."""
    return starter(connect(url))


def rerun(url: str) -> Callable[[str, Mapping[str, str]], str]:
    """The rerun capability of the Dagu instance at `url`: start a workflow with parameters."""
    return rerunner(connect(url))


def _refresh_stats_forever(url: str, stats: dict, stop: threading.Event) -> None:
    """Read the run statistics of Dagu's DAGs every `RECONCILE_INTERVAL` seconds until `stop`; a read that fails is tried again after `STATS_TTL`."""
    tried: dict = {}
    while True:
        try:
            refresh_stats(url, stats, tried=tried)
        except OSError, ValueError, KeyError, TypeError:  # Dagu unreachable or answering something else
            pass
        if stop.wait(RECONCILE_INTERVAL):
            return


def _reconcile_forever(runs: DaguRuns, stop: threading.Event) -> None:
    """List Dagu every `RECONCILE_INTERVAL` seconds until `stop`, so runs show with no `handler_on` hooks publishing them."""
    while True:
        runs.reconcile()
        if stop.wait(RECONCILE_INTERVAL):
            return


def follow(
    url: str,
    runs: RunsSink,
    log: EventLog,
    *,
    interval: float = DEFAULT_POLL_INTERVAL,
    stop: threading.Event | None = None,
) -> None:
    """Read the Dagu instance at `url` into `runs`: its listing, then each run entry appended since the log's head.

    The head is read before the listing, so an entry the listing may not hold is still read and the retained ones,
    already in it, are not replayed; an entry stamped before the listing is dropped (`DaguRuns`). The listing
    repeats every `RECONCILE_INTERVAL` seconds, so runs show with no `handler_on` hooks publishing them. A sink with a `tied`
    attribute (the workflows a Board event cues or that write one) also gets those workflows' recent runs. A third thread
    reads the DAGs' run statistics apart from the listing (`refresh_stats`), which serves them as they are read. The
    threads end when `stop` is set; the server passes none and they run for the process's life.
    """
    stop = stop or threading.Event()
    tied = lambda: getattr(runs, "tied", frozenset())  # noqa: E731
    finished: dict = {}
    graphs: dict = {}
    stats: dict = {}
    reader = DaguRuns(
        runs,
        lambda only=None: dags(url, only, tied(), finished, graphs, stats=stats),
        lambda: pools(url),
        cpu=CpuSampler(),
        tied=tied,
        instance=getattr(runs, "instance", None),
    )

    def read() -> None:
        tail = Tail.live(log, run_events.STREAM, interval=interval)  # before the listing: what it holds is not replayed
        reader.reconcile()
        tail.run(lambda entry: reader.handle_entry(str(entry.id), entry.fields), stop)

    threading.Thread(target=read, name="dagu-runs", daemon=True).start()
    threading.Thread(target=_reconcile_forever, args=(reader, stop), name="dagu-runs-reconcile", daemon=True).start()
    threading.Thread(
        target=_refresh_stats_forever, args=(url, stats, stop), name="dagu-runs-stats", daemon=True
    ).start()
