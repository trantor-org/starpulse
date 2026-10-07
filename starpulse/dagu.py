"""The Dagu adapter: each DAG's step graph and latest run, as the `runs` contract's `Dag` records.

`dags` reads one Dagu instance, by URL, into those records. `start` and `follow` are what a runs adapter module
offers the server for one configured instance: its start capability, and the reading of its workflows. The page used to poll Dagu: one listing
plus one request per DAG every few seconds. Dagu's `handler_on` hooks now publish each run's start and end
through `starpulse emit`, so one listing at start and at every reconnect gives each DAG its step graph
and latest run, and the entries on the runs stream after it move them (`DaguRuns`). A listing every 30 s keeps
the page right for a run no entry reported, such as one on a Dagu without the hooks.
"""

from __future__ import annotations

import json
import math
import re
import shlex
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, get_args

from starpulse import run_events
from starpulse.contracts import RunsSink, RunStatus, StartFailedError
from starpulse.event_log import DEFAULT_POLL_INTERVAL, EventLog, Tail

#: Seconds between two listings of a followed Dagu instance.
RECONCILE_INTERVAL = 30.0

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
    """The adapter's start capability: asks Dagu to start a DAG and returns the run's id."""
    return lambda dag: _launch(transport, dag, {})


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


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.load(resp)


def _steps(base_url: str, name: str) -> tuple[str, list[dict]]:
    """The queue a DAG declares, and its steps: each with the steps it waits on, its status in the latest run and its declared kind."""
    detail = _get(f"{base_url}/api/v1/dags/{name}")
    ran = {n["step"]["name"]: n["statusLabel"] for n in (detail.get("latestDAGRun") or {}).get("nodes", [])}
    return detail["dag"].get("queue", ""), [
        {
            "name": s["name"],
            "depends": s.get("depends", []),
            **_reported(ran.get(s["name"], "not_started")),
            "kind": _kind(s),
        }
        for s in detail["dag"].get("steps", [])
    ]


def declared_params(base_url: str, name: str) -> list[str]:
    """The names of the parameters DAG `name` declares; Dagu reports each as `NAME=default`."""
    detail = _get(f"{base_url}/api/v1/dags/{urllib.parse.quote(name)}")
    return [word.partition("=")[0] for word in detail["dag"].get("params", []) if "=" in word]


def _kind(step: dict) -> str | None:
    """The phase kind a rendered step declares as its description (`kind: agent`), else None."""
    description = step.get("description", "")  # pragma: no mutate: a default lacking the prefix is equivalent
    if not description.startswith("kind: "):
        return None
    return description.removeprefix("kind: ").strip() or None


#: Dagu's numeric run statuses, as `/dag-runs?status=` filters by them.
_RUNNING, _QUEUED = 1, 5
#: How far back `/dag-runs` looks for runs still in flight; without a `fromDate` it starts at UTC midnight.
_IN_FLIGHT_LOOKBACK = 7 * 86400


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
    """Each DAG's running runs, longest-running first, then its queued ones, oldest first; none when Dagu cannot list them."""
    out: dict[str, list[dict]] = {}
    since = int(time.time()) - _IN_FLIGHT_LOOKBACK
    try:
        for status, begun in ((_RUNNING, "startedAt"), (_QUEUED, "queuedAt")):
            listed = _get(f"{base_url}/api/v1/dag-runs?status={status}&perPage=200&fromDate={since}").get("dagRuns", [])
            for run in sorted(listed, key=lambda r: r.get(begun, "")):
                out.setdefault(run["name"], []).append(run)
    except OSError:
        return {}
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


def _recent_run(base_url: str, run: dict) -> dict:
    """One listed run as a `RecentRun`, its steps read from its detail (none when Dagu no longer has it)."""
    try:
        nodes = _get(f"{base_url}/api/v1/dag-runs/{run['name']}/{run['dagRunId']}")["dagRunDetails"].get("nodes", [])
    except OSError:
        nodes = []
    return {
        "runId": run["dagRunId"],
        **_reported(run["statusLabel"]),
        "startedAt": run.get("startedAt") or run.get("queuedAt") or "",
        "finishedAt": run.get("finishedAt", ""),
        "params": _params(run.get("params", "")),
        "steps": {n["step"]["name"]: status_of(n["statusLabel"]) for n in nodes},
    }


def recent_runs(base_url: str, name: str, finished: dict | None = None) -> list[dict]:
    """The last day's runs of DAG `name` as `RecentRun` records, in the order Dagu lists them (newest first).

    A run that is over keeps the steps it was read with in `finished`, so only runs in flight cost a detail read; the
    entries of `name` that Dagu no longer lists leave it. A listing Dagu cannot give is none.
    """
    cache = {} if finished is None else finished
    since, cursor, runs = int(time.time()) - _RECENT_LOOKBACK, "", []
    try:
        while True:
            more = f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""
            page = _get(f"{base_url}/api/v1/dag-runs?name={urllib.parse.quote(name)}&perPage={_PAGE}&fromDate={since}{more}")
            runs += page.get("dagRuns", [])
            if not (cursor := page.get("nextCursor") or ""):
                break
    except OSError:
        return []
    out = []
    for run in runs:
        key = (name, run["dagRunId"])
        out.append(cache[key] if key in cache else _recent_run(base_url, run))
        if out[-1]["status"] not in _OPEN:
            cache[key] = out[-1]
    live = {(name, run["dagRunId"]) for run in runs}
    for key in [k for k in cache if k[0] == name and k not in live]:
        del cache[key]
    return out


def dags(
    base_url: str, only: Collection[str] | None = None, recent: Collection[str] = (), finished: dict | None = None
) -> list[dict]:
    """Every DAG on a Dagu instance, or just those in `only`, with its latest run, its step graph and its pool.

    A full listing also reads each DAG's active runs; the listing of `only` leaves them out, as it serves a step read
    after one run entry. A DAG whose detail cannot be read is listed without steps or pool rather than failing the listing.
    """
    in_flight = _in_flight(base_url) if only is None else {}
    out = []
    for d in _get(f"{base_url}/api/v1/dags?perPage=200").get("dags", []):
        if only is not None and d["fileName"] not in only:
            continue
        try:
            pool, steps = _steps(base_url, d["fileName"])
        except OSError:
            pool, steps = "", []
        run = d.get("latestDAGRun") or {}
        out.append(
            {
                "name": d["fileName"],
                **_reported(run.get("statusLabel") or "not_started"),
                "runId": run.get("dagRunId", ""),
                "startedAt": run.get("startedAt") or run.get("queuedAt") or "",
                "finishedAt": run.get("finishedAt", ""),
                "steps": steps,
                "active": [a for r in in_flight.get(d["fileName"], []) if (a := _active(base_url, r, steps))],
                "pool": pool,
                **({"recent": recent_runs(base_url, d["fileName"], finished)} if d["fileName"] in recent else {}),
            }
        )
    return out


@dataclass(frozen=True)
class _Run:
    """One decoded run entry of the runs stream."""

    phase: str
    dag: str
    run_id: str
    status: str
    at: float
    step: str


def _decode(fields: dict) -> _Run | None:
    """The run (or, with `step`, the step of a run) an entry reports, or None for one the contract does not allow."""
    try:
        run = _Run(
            fields["phase"],
            fields["workflow"],
            fields["run_id"],
            fields["status"],
            float(fields["time"]),
            fields.get("step") or "",
        )
    except KeyError, ValueError:
        return None
    well_formed = run.phase in run_events.PHASES and run.status in get_args(RunStatus)
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
            elif run.phase != "start":
                entry = _restated(entry, run.status) | {"finishedAt": _iso(run.at)}
        out.append(entry)
    return out


def _begun(recent: list[dict], run: _Run) -> list[dict]:
    """`recent` holding the run a start entry reports, with no parameters when Dagu has not listed it yet."""
    if any(entry["runId"] == run.run_id for entry in recent):
        return recent
    begun = {"runId": run.run_id, "status": "running", "startedAt": _iso(run.at), "finishedAt": "", "params": {}, "steps": {}}
    return [begun, *recent]


class DaguRuns:
    """The DAGs as the page draws them, from `fetch` (one Dagu listing, of the named DAGs or all) and then run entries.

    `pools` reads the instance's concurrency pools alongside each full listing. `tied` names the workflows whose
    recent runs (`Dag.recent`) are kept: `fetch` reads them with each listing, and an entry moves them in step with
    the run it reports, a start reading the run once more for the parameters it began with.

    Entries and reconnects arrive on the consumer thread and the periodic reconcile runs on its own, so the
    DAGs are held under a lock; the sink holds the page-facing state and its own.
    """

    def __init__(
        self,
        sink: RunsSink,
        fetch: Callable[[Collection[str] | None], list],
        pools: Callable[[], list[dict]] = list,
        *,
        tied: Callable[[], Collection[str]] = frozenset,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sink = sink
        self._fetch = fetch
        self._pools = pools
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
            self._sink.set_dags(list(self._dags.values()), None, pools)

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
        if run is None or fields.get("instance") or run.at < self._listed_at:  # an ingested entry is another instance's
            return
        dag = self._dags.get(run.dag)
        if dag is None:  # a DAG file added since the listing
            listed_at = self._clock()
            dag = self._listed(run.dag)
            if dag is None:
                return
            self._dags[run.dag] = dag
            if run.at < listed_at:  # the entry is already in what Dagu just listed
                self._sink.set_dags(list(self._dags.values()), None)
                return
        others = [a for a in dag.get("active", []) if a["runId"] != run.run_id]
        tied = run.dag in self._tied()
        known = any(r["runId"] == run.run_id for r in dag.get("recent", []))
        fresh = None  # the recent runs as Dagu lists them, when this entry made a listing necessary
        if run.step:
            moved = _stepped(dag, run) or (dag if tied and known else None)
            if moved is None:
                return  # a step of a run that is neither in flight nor the one drawn
        elif run.phase == "start":
            if tied and (listed := self._listed(run.dag)):
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
        elif run.run_id == dag["runId"]:
            # Dagu is still inside the run's exit handler, so only its steps are final: read them now.
            listed = self._listed(run.dag)
            fresh = listed.get("recent") if listed else None
            moved = _restated(dag, run.status) | {
                "finishedAt": _iso(run.at),
                "steps": listed["steps"] if listed else dag["steps"],
                "active": others,
            }
        elif len(others) < len(dag.get("active", [])):
            moved = {**dag, "active": others}  # the end of a run no longer the one drawn, still listed as active
        elif tied and known:
            moved = dag  # no longer the one drawn, and not active, but a run the ledger still holds
        else:
            return  # the end of a run that is no longer the one drawn
        if tied:
            recent = fresh if fresh is not None else _patched(dag.get("recent", []), run)
            moved = {**moved, "recent": _begun(recent, run) if run.phase == "start" and not run.step else recent}
        self._dags[run.dag] = moved
        self._streamed[run.dag] = run.at
        self._sink.set_dags(list(self._dags.values()), None)


def start(url: str) -> Callable[[str], str]:
    """The start capability of the Dagu instance at `url`."""
    return starter(connect(url))


def rerun(url: str) -> Callable[[str, Mapping[str, str]], str]:
    """The rerun capability of the Dagu instance at `url`: start a workflow with parameters."""
    return rerunner(connect(url))


def _reconcile_forever(runs: DaguRuns) -> None:
    """List Dagu every `RECONCILE_INTERVAL` seconds, so runs show with no `handler_on` hooks publishing them."""
    while True:
        runs.reconcile()
        time.sleep(RECONCILE_INTERVAL)


def follow(url: str, runs: RunsSink, log: EventLog, *, interval: float = DEFAULT_POLL_INTERVAL) -> None:
    """Read the Dagu instance at `url` into `runs`: its listing, then the run entries the log retains and each new one.

    The listing comes first so an entry stamped before it, already in it, is dropped (`DaguRuns`); it repeats every
    `RECONCILE_INTERVAL` seconds, so runs show with no `handler_on` hooks publishing them. A sink with a `tied`
    attribute (the workflows a Board event cues or that write one) also gets those workflows' recent runs.
    """
    tied = lambda: getattr(runs, "tied", frozenset())  # noqa: E731
    finished: dict = {}
    reader = DaguRuns(runs, lambda only=None: dags(url, only, tied(), finished), lambda: pools(url), tied=tied)

    def read() -> None:
        reader.reconcile()
        Tail(log, run_events.STREAM, interval=interval).run(
            lambda entry: reader.handle_entry(str(entry.id), entry.fields), threading.Event()
        )

    threading.Thread(target=read, name="dagu-runs", daemon=True).start()
    threading.Thread(target=_reconcile_forever, args=(reader,), name="dagu-runs-reconcile", daemon=True).start()
