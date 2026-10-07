"""A Dagu API on an ephemeral port that counts the requests it gets, and `runs:events` entries as a consumer reads them."""

import itertools
import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

_ids = itertools.count(1)  # Event ids rise; each entry built here takes the next


@dataclass(frozen=True)
class Queue:
    """One Dagu queue as `/api/v1/queues` reports it."""

    cap: int
    running: int = 0
    queued: int = 0


@dataclass(frozen=True)
class InFlight:
    """One run of a DAG that is running or queued, with its steps as `(name, label, startedAt)`."""

    dag: str
    run_id: str
    label: str = "running"
    started_at: str = ""
    queued_at: str = "2026-10-02T17:00:00Z"
    nodes: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Past:
    """One run in a DAG's history as `/api/v1/dag-runs?name=` lists it, its steps as `(name, label)` and its params as Dagu prints them."""

    dag: str
    run_id: str
    label: str = "succeeded"
    started_at: str = ""
    finished_at: str = ""
    params: str = ""
    nodes: tuple[tuple[str, str], ...] = ()


#: Dagu's numeric run statuses, as `/dag-runs?status=` filters by them.
_STATUS_OF = {"running": 1, "queued": 5}


@contextmanager
def dagu(
    steps: dict[str, list[str]],
    labels: dict[str, str] | None = None,
    latest: dict[str, str] | None = None,
    *,
    queues: dict[str, Queue] | None = None,
    queue_of: dict[str, str] | None = None,
    in_flight: tuple[InFlight, ...] = (),
    listed_since: str = "",
    history: Sequence[Past] = (),
    page: int = 100,
) -> Iterator[tuple[str, list[str]]]:
    """Serve one DAG per key of `steps` (its value is the step names, each depending on the one before).

    A step reports `succeeded` in the latest run unless `labels` (read at each request) names its label.
    The listing gives every DAG the `latest` run (a dict the caller may change while the server runs), a
    succeeded `r0` unless given. `queues` are the queues `/queues` reports (a Dagu without them answers 404),
    `queue_of` the queue each DAG declares, and `in_flight` the runs `/dag-runs` lists as running or queued.
    Like Dagu, whose listing starts at UTC midnight unless asked for a `fromDate`, a listing with no `fromDate` leaves
    out the runs that began before `listed_since`. `history` (read at each request, so a caller may add to it) are the runs `/dag-runs?name=` lists, `page` at a time with
    a `nextCursor` while more remain; their detail is served like an in-flight run's.
    Yields the base URL and the list of every request path received, in order.
    """
    calls: list[str] = []
    step_labels: dict[str, str] = {} if labels is None else labels
    run: dict[str, str] = {"statusLabel": "succeeded", "dagRunId": "r0"} if latest is None else latest

    def detail(name: str) -> dict:
        return {
            "dag": {
                "steps": [{"name": s, "depends": steps[name][i - 1 : i]} for i, s in enumerate(steps[name])],
                **({"queue": queue_of[name]} if queue_of and name in queue_of else {}),
            },
            "latestDAGRun": {
                "nodes": [{"step": {"name": s}, "statusLabel": step_labels.get(s, "succeeded")} for s in steps[name]]
            },
        }

    def summary(r: InFlight) -> dict:
        return {
            "name": r.dag,
            "dagRunId": r.run_id,
            "statusLabel": r.label,
            "startedAt": r.started_at,
            "queuedAt": r.queued_at,
        }

    def run_detail(r: InFlight) -> dict:
        nodes = [{"step": {"name": n}, "statusLabel": label, "startedAt": at} for n, label, at in r.nodes]
        return {"dagRunDetails": {**summary(r), "nodes": nodes}}

    def past_summary(r: Past) -> dict:
        return {
            "name": r.dag,
            "dagRunId": r.run_id,
            "statusLabel": r.label,
            "startedAt": r.started_at,
            "finishedAt": r.finished_at,
            "params": r.params,
        }

    def past_detail(r: Past) -> dict:
        nodes = [{"step": {"name": n}, "statusLabel": label} for n, label in r.nodes]
        return {"dagRunDetails": {**past_summary(r), "nodes": nodes}}

    def answer(path: str) -> tuple[int, dict]:
        url = urlsplit(path)
        parts = url.path.removeprefix("/api/v1/").split("/")
        if path == "/api/v1/dags?perPage=200":
            return 200, {"dags": [{"fileName": n, "latestDAGRun": {**run}} for n in steps]}
        if parts == ["queues"]:
            if queues is None:
                return 404, {}
            return 200, {
                "queues": [
                    {"name": n, "maxConcurrency": q.cap, "runningCount": q.running, "queuedCount": q.queued}
                    for n, q in queues.items()
                ]
            }
        if parts == ["dag-runs"] and "name" in parse_qs(url.query):
            query = parse_qs(url.query)
            mine = [r for r in history if r.dag == query["name"][0]]
            first = int(query.get("cursor", ["0"])[0])
            more = first + page < len(mine)
            return 200, {
                "dagRuns": [past_summary(r) for r in mine[first : first + page]],
                **({"nextCursor": str(first + page)} if more else {}),
            }
        if parts == ["dag-runs"]:
            query = parse_qs(url.query)
            status = int(query["status"][0])
            since = "" if "fromDate" in query else listed_since
            listed = [r for r in in_flight if _STATUS_OF[r.label] == status and (r.started_at or r.queued_at) >= since]
            return 200, {"dagRuns": [summary(r) for r in listed]}
        if parts[0] == "dag-runs":
            if found := next((r for r in history if (r.dag, r.run_id) == (parts[1], parts[2])), None):
                return 200, past_detail(found)
            return 200, run_detail(next(r for r in in_flight if (r.dag, r.run_id) == (parts[1], parts[2])))
        return 200, detail(parts[1])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            calls.append(self.path)
            code, payload = answer(self.path)
            self.send_response(code)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()


def run_entry(phase: str, workflow: str, run_id: str, status: str, at: float) -> tuple:
    """`(stream id, fields)` for one `runs:events` entry, its values strings as `StreamProducer` writes them."""
    fields = {"event_id": f"{workflow}-{run_id}-{phase}", "time": str(at), "phase": phase, "workflow": workflow}
    fields |= {"run_id": run_id, "status": status}
    return f"{next(_ids)}-0", fields


def step_entry(phase: str, workflow: str, run_id: str, step: str, status: str, at: float) -> tuple:
    """`(stream id, fields)` for one `runs:events` entry about a step of a run."""
    entry_id, fields = run_entry(phase, workflow, run_id, status, at)
    return entry_id, fields | {"event_id": f"{workflow}-{run_id}-{step}-{phase}", "step": step}
