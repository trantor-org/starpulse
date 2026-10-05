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
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection
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


def starter(transport: Transport) -> Callable[[str], str]:
    """The adapter's start capability: asks Dagu to start a DAG and returns the run's id."""

    def start(dag: str) -> str:
        status, body = transport("POST", f"/dags/{dag}/start", {})
        if status != 200 or not body.get("dagRunId"):
            raise StartFailedError(f"Dagu refused the start (HTTP {status})")
        return body["dagRunId"]

    return start


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.load(resp)


def _steps(base_url: str, name: str) -> list[dict]:
    """A DAG's steps, each with the steps it waits on, its status in the latest run and its declared kind."""
    detail = _get(f"{base_url}/api/v1/dags/{name}")
    ran = {n["step"]["name"]: n["statusLabel"] for n in (detail.get("latestDAGRun") or {}).get("nodes", [])}
    return [
        {
            "name": s["name"],
            "depends": s.get("depends", []),
            **_reported(ran.get(s["name"], "not_started")),
            "kind": _kind(s),
        }
        for s in detail["dag"].get("steps", [])
    ]


def _kind(step: dict) -> str | None:
    """The phase kind a rendered step declares as its description (`kind: agent`), else None."""
    description = step.get("description", "")  # pragma: no mutate: a default lacking the prefix is equivalent
    if not description.startswith("kind: "):
        return None
    return description.removeprefix("kind: ").strip() or None


def dags(base_url: str, only: Collection[str] | None = None) -> list[dict]:
    """Every DAG on a Dagu instance, or just those in `only`, with its latest run and its step graph.

    A DAG whose detail cannot be read is listed without steps rather than failing the listing.
    """
    out = []
    for d in _get(f"{base_url}/api/v1/dags?perPage=200").get("dags", []):
        if only is not None and d["fileName"] not in only:
            continue
        try:
            steps = _steps(base_url, d["fileName"])
        except OSError:
            steps = []
        run = d.get("latestDAGRun") or {}
        out.append(
            {
                "name": d["fileName"],
                **_reported(run.get("statusLabel") or "not_started"),
                "runId": run.get("dagRunId", ""),
                "startedAt": run.get("startedAt") or run.get("queuedAt") or "",
                "finishedAt": run.get("finishedAt", ""),
                "steps": steps,
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


def _decode(fields: dict) -> _Run | None:
    """The run an entry reports, or None for one the contract does not allow or one that reports a step."""
    try:
        run = _Run(fields["phase"], fields["workflow"], fields["run_id"], fields["status"], float(fields["time"]))
    except KeyError, ValueError:
        return None
    well_formed = run.phase in run_events.PHASES and run.status in get_args(RunStatus) and not fields.get("step")
    return run if well_formed else None


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class DaguRuns:
    """The DAGs as the page draws them, from `fetch` (one Dagu listing, of the named DAGs or all) and then run entries.

    Entries and reconnects arrive on the consumer thread and the periodic reconcile runs on its own, so the
    DAGs are held under a lock; the sink holds the page-facing state and its own.
    """

    def __init__(
        self, sink: RunsSink, fetch: Callable[[Collection[str] | None], list], *, clock: Callable[[], float] = time.time
    ) -> None:
        self._sink = sink
        self._fetch = fetch
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
            self._sink.set_dags(list(self._dags.values()), None)

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
        if run is None or run.at < self._listed_at:
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
        if run.phase == "start":
            moved = _restated(dag, "running") | {
                "runId": run.run_id,
                "startedAt": _iso(run.at),
                "finishedAt": "",
                "steps": [_restated(step, "not_started") for step in dag["steps"]],
            }
        elif run.run_id == dag["runId"]:
            # Dagu is still inside the run's exit handler, so only its steps are final: read them now.
            listed = self._listed(run.dag)
            moved = _restated(dag, run.status) | {
                "finishedAt": _iso(run.at),
                "steps": listed["steps"] if listed else dag["steps"],
            }
        else:
            return  # the end of a run that is no longer the one drawn
        self._dags[run.dag] = moved
        self._streamed[run.dag] = run.at
        self._sink.set_dags(list(self._dags.values()), None)


def start(url: str) -> Callable[[str], str]:
    """The start capability of the Dagu instance at `url`."""
    return starter(connect(url))


def _reconcile_forever(runs: DaguRuns) -> None:
    """List Dagu every `RECONCILE_INTERVAL` seconds, so runs show with no `handler_on` hooks publishing them."""
    while True:
        runs.reconcile()
        time.sleep(RECONCILE_INTERVAL)


def follow(url: str, runs: RunsSink, log: EventLog, *, interval: float = DEFAULT_POLL_INTERVAL) -> None:
    """Read the Dagu instance at `url` into `runs`: its listing, then the run entries the log retains and each new one.

    The listing comes first so an entry stamped before it, already in it, is dropped (`DaguRuns`); it repeats every
    `RECONCILE_INTERVAL` seconds, so runs show with no `handler_on` hooks publishing them.
    """
    reader = DaguRuns(runs, lambda only=None: dags(url, only))

    def read() -> None:
        reader.reconcile()
        Tail(log, run_events.STREAM, interval=interval).run(
            lambda entry: reader.handle_entry(str(entry.id), entry.fields), threading.Event()
        )

    threading.Thread(target=read, name="dagu-runs", daemon=True).start()
    threading.Thread(target=_reconcile_forever, args=(reader,), name="dagu-runs-reconcile", daemon=True).start()
