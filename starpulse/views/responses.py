"""The read routes' bodies and statuses: each takes the stores it reads and answers `(bytes, status)`."""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.board.ledger import PAGE
from starpulse.board.model.seam import (
    TaskReader,
)
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.flow_metrics import analytics
from starpulse.flow_metrics.cells import cell_report, transition_cost
from starpulse.flow_metrics.clusters import Cluster, cluster_key, dispersion, trace, trace_clusters
from starpulse.flow_metrics.flow import cost_to_go, directly_follows, fast_slow_diff, sub_stages
from starpulse.flow_metrics.level_metrics import WindowPastHistory
from starpulse.flow_metrics.session_health import session_health, slice_health
from starpulse.flow_metrics.steps import session_steps
from starpulse.flow_metrics.traces import Case, missed_loads
from starpulse.flow_metrics.traces import cases as trace_cases
from starpulse.harness_telemetry.telemetry import Signal, TelemetryLog
from starpulse.machine_engine.model.stays import lane_stays
from starpulse.views.encoding import encode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.search import SearchIndex
    from starpulse.board.board_feed import BoardFeed
    from starpulse.flow_metrics.history import History
    from starpulse.pulls.pulls import PullStore


#: The most rows `/api/ledger/<event>` and `/api/machines` serve at once.
_PAGE_LIMIT = 100


def _error(message: str) -> bytes:
    return encode("error", {"error": message})


def _page_query(query: dict[str, list[str]], noun: str) -> tuple[float | None, int] | bytes:
    """The `before` and `limit` of a paged route, or the 400 body for one that is malformed."""
    try:
        before = float(query["before"][0]) if "before" in query else None
        limit = int(query["limit"][0]) if "limit" in query else PAGE
    except ValueError:
        return _error(f"{noun} takes a numeric ?before= and an integer ?limit=")
    if before is not None and not math.isfinite(before) or not 0 < limit <= _PAGE_LIMIT:
        return _error(f"{noun} takes a finite ?before= and a ?limit= from 1 to {_PAGE_LIMIT}")
    return before, limit


def ledger_response(feed: BoardFeed, event: str, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/ledger/<event>`: that Ledger's next page, older than `before`, at most `limit`
    long; 404 for an event no workflow is tied to."""
    asked = _page_query(query, "ledger")
    if isinstance(asked, bytes):
        return asked, 400
    if (found := feed.ledger_rows(event, *asked)) is None:
        return _error(f"no ledger for {event}"), 404
    return encode("ledger", found), 200


def machines_response(feed: BoardFeed, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/machines`: the next page of machines entered from `open`, older than `before`."""
    asked = _page_query(query, "machines")
    if isinstance(asked, bytes):
        return asked, 400
    open_ = query["open"][0] if "open" in query else None
    found = feed.machine_rows(open_, *asked)
    if found is None:
        return _error(f"{open_} is not a machine here"), 404
    return encode("machines", found), 200


def done_response(feed: BoardFeed, read: TaskReader | None, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/done`: the next page of cold done tasks, each read from the board for its card."""
    if read is None:
        return _error("this board cannot read a task's full record"), 404
    asked = _page_query(query, "done")
    if isinstance(asked, bytes):
        return asked, 400
    stubs, more = feed.cold_page(*asked)
    tasks = [_done_card(stub, read(stub["id"]) or {}) for stub in stubs]
    return encode("done", {"tasks": tasks, "more": more}), 200


def _done_card(stub: dict, record: Mapping[str, Any]) -> dict:
    """A kanban card for a cold done task: its stub's id and entered time with the card fields of its board record."""
    card = {key: record[key] for key in ("labels", "milestone", "type") if key in record}
    named = {"id": stub["id"], "title": record.get("title") or stub["id"], "state": "done"}
    return named | {"model": record.get("profile") or "", "entered": stub["entered"]} | card


def history_response(
    history: History,
    query: dict[str, list[str]],
    flows: Collection[str],
    keys: TaskKeys | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[bytes, int]:
    """The body and status for `/api/history`: a task's lane path, with `machine` its path on that machine, or with
    `hours` every machine event of the task in that window, oldest first, as `{at, machine, event, from, to}`.

    `flows` are the machines the page draws; a task is looked up under the spelling `keys` gives it."""
    task, flow = (query.get(key, [""])[0] for key in ("task", "machine"))
    task = keys.canonical(task) if keys else task
    if not task:
        return _error("history needs ?task=TASK-N"), 400
    if flow and flow not in flows:
        return _error(f"unknown machine {flow}"), 404
    body: dict[str, Any] = {"task": task}
    if flow:
        body |= {"machine": flow}
        body["path"], body["steps"] = history.machine_path(task, flow)
    elif "hours" in query:
        hours = _hours(query, "hours", 0.0)
        if hours is None:
            return _error("hours must be a positive number"), 400
        at = now()
        body |= {"hours": hours, "events": history.task_events(task, at - hours * 3600, at)}
    else:
        body["path"] = history.lane_path(task)
    return encode("history", body), 200


def pulls_response(pulls: PullStore | None, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/pulls`: the stored pull requests matching every filter given.

    A `number` that is not an integer, or a `state` that is not open, merged or closed, is 400."""
    state = query.get("state", [""])[0].upper() or None
    try:
        number = int(query["number"][0]) if "number" in query else None
    except ValueError:
        return _error("pulls takes an integer ?number="), 400
    if state not in (None, "OPEN", "MERGED", "CLOSED"):
        return _error("pulls takes ?state= open, merged or closed"), 400
    found = (
        pulls.find(query.get("repo", [""])[0] or None, number, state, query.get("body_contains", [""])[0] or None)
        if pulls
        else []
    )
    return encode("pulls", {"pulls": found}), 200


#: A GitHub pull request URL, which a task cites in its references: its `owner/repo` and number.
_PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")


def cited_pulls(pulls: PullStore | None, references: list[str]) -> list[dict[str, Any]]:
    """The stored pull requests `references` cite, without their bodies: each one's state and checks, so a task
    record shows them as the pull requests page does."""
    if not pulls:
        return []
    cited = [match for ref in references if (match := _PULL_URL.fullmatch(ref))]
    return [
        {key: value for key, value in record.items() if key != "body"}
        for match in cited
        for record in pulls.find(match[1], int(match[2]))
    ]


#: `/api/search`'s default and largest number of hits.
_SEARCH_HITS = 10


_SEARCH_LIMIT = 100


def search_response(search: SearchIndex | None, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/search`: the tasks holding every word of `?q=`, best first, at most `?limit=`;
    each repeated `?label=` keeps only the tasks carrying it, and `?finished_within_days=` drops a task that finished
    (settled, or entered the done lane) longer ago than that many days.

    A server with no index is 404; a blank `q`, a `limit` that is not an integer from 1 to 100 or a
    `finished_within_days` that is not a positive integer is 400."""
    if search is None:
        return _error("this server keeps no search index"), 404
    words = query.get("q", [""])[0].strip()
    try:
        limit = int(query["limit"][0]) if "limit" in query else _SEARCH_HITS
    except ValueError:
        limit = 0
    try:
        days = int(query["finished_within_days"][0]) if "finished_within_days" in query else None
    except ValueError:
        days = 0
    if not words or not 0 < limit <= _SEARCH_LIMIT or (days is not None and days < 1):
        return _error(
            f"search takes a ?q= of words, a ?limit= from 1 to {_SEARCH_LIMIT} and a positive ?finished_within_days="
        ), 400
    since = None if days is None else time.time() - days * 86400
    hits = search.search(words, limit, labels=query.get("label", []), finished_since=since)
    return encode("search", {"query": words, "hits": hits}), 200


#: `/api/analytics/health`'s defaults: the window it counts over, and how long a stay in one state makes a task stuck.
_HEALTH_HOURS = 168.0


_STUCK_HOURS = 24.0


def _hours(query: dict[str, list[str]], key: str, default: float) -> float | None:
    """The positive, finite number of hours `key` gives, `default` when absent; None for anything else."""
    try:
        hours = float(query[key][0]) if key in query else default
    except ValueError:
        return None
    return hours if 0 < hours < float("inf") else None


def health_response(
    history: History, query: dict[str, list[str]], machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/health`: the Board's flow health over the last `hours` as of `now`."""
    from starpulse.flow_metrics.history import HealthHistory, SummarisedHealth  # noqa: PLC0415 - the database stack loads when a store does

    window = _hours(query, "hours", _HEALTH_HOURS)
    stuck = _hours(query, "stuck_hours", _STUCK_HOURS)
    if window is None or stuck is None:
        return _error("hours and stuck_hours must each be a positive number"), 400
    if not isinstance(history, HealthHistory):
        return _error("this history does not keep every task's lane changes, so it cannot report flow health"), 501
    start = now - window * 3600
    if isinstance(history, SummarisedHealth):
        held = history.health_stays(machines["board"], start=start, now=now, stuck_s=stuck * 3600)
    else:
        held = lane_stays(history.lane_rows(), start=start, now=now, stuck_s=stuck * 3600)
    health = analytics.stay_health(
        machines["board"], held, history.gaps(), now=now, window_s=window * 3600, stuck_s=stuck * 3600
    )
    return encode("health", health), 200


def _held_signals(
    telemetry: TelemetryLog, window: float, kind: str, now: float, label: str
) -> list[Signal] | tuple[bytes, int]:
    """The signals from the last `window` hours as of `now`, or the 503 response for a log that cannot be read.

    The oldest signal the log holds is where its history begins: a window that starts before it is 400 with the
    history's length (`history_s`), never answered with its missing hours as empty, as `level_response` refuses one."""
    try:
        held = telemetry.read()
    except Exception as exc:  # the event log's database is unreachable
        logger.warning("%s: telemetry unreadable: %s", label, exc)
        return _error("the telemetry log cannot be read"), 503
    history = now - min((s.time for s in held), default=now)
    if window * 3600 > history:
        return encode(kind, {"error": str(WindowPastHistory(window * 3600, history)), "history_s": history}), 400
    return [s for s in held if s.time >= now - window * 3600]


def sessions_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/sessions`: session and slice health of the signals from the last
    `hours` (default 168) as of `now`. An instance that receives no harness telemetry is 501, a log that cannot be
    read 503, and a window longer than the telemetry history 400 with `history_s` its length."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot report session health"), 501
    found = _held_signals(telemetry, window, "sessions", now, "sessions")
    if isinstance(found, tuple):
        return found
    rows = session_health(found, keys, analytics)
    body = {"now": now, "window_s": window * 3600, "sessions": rows, "slices": slice_health(rows)}
    return encode("sessions", body), 200


def steps_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/steps`: every model request of the signals from the last `hours`
    (default 168) as of `now`. An instance that receives no harness telemetry is 501, a log that cannot be read 503,
    and a window longer than the telemetry history 400 with `history_s` its length."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot report session steps"), 501
    found = _held_signals(telemetry, window, "session_steps", now, "steps")
    if isinstance(found, tuple):
        return found
    return encode(
        "session_steps", {"now": now, "window_s": window * 3600, "steps": session_steps(found, keys, analytics)}
    ), 200


def _kind_size_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    now: float,
    label: str,
    report: Callable[[list[Signal], float], list[dict[str, Any]]],
    span: int = 1,
) -> tuple[bytes, int]:
    """The body and status for a report by kind and size of the signals from the last `span` x `hours` (default 168
    each) as of `now`, keyed `label`: `{now, window_s, <label>: report(signals, since)}`, `since` the start of the
    last `hours`. An instance that receives no harness telemetry is 501, a log that cannot be read 503, and a window
    longer than the telemetry history 400 with `history_s`."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error(f"this instance receives no harness telemetry, so it cannot report {label}"), 501
    found = _held_signals(telemetry, window * span, label, now, label)
    if isinstance(found, tuple):
        return found
    return encode(label, {"now": now, "window_s": window * 3600, label: report(found, now - window * 3600)}), 200


def transitions_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/transitions`: the cost of each skill within each kind and size
    (`cells.transition_cost`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "transitions", lambda found, _: transition_cost(found, keys, titled(), analytics)
    )


def cells_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/cells`: the median steps per clean completion of each kind and size
    (`cells.cell_report`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry,
        query,
        now,
        "cells",
        lambda found, _: cell_report(slice_health(session_health(found, keys, analytics)), titled()),
    )


def graph_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/graph`: the branching directly-follows graph of each transition
    (`flow.directly_follows`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "graph", lambda found, _: directly_follows(found, keys, titled(), analytics)
    )


def stages_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/stages`: the sub-stages mined from the last `hours` against the
    `hours` before them (`flow.sub_stages`), so the history must hold twice the window; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry,
        query,
        now,
        "stages",
        lambda found, since: sub_stages(found, keys, titled(), analytics, since=since),
        span=2,
    )


def diff_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/diff`: each transition's reference run against its slowest clean run
    (`flow.fast_slow_diff`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "diff", lambda found, _: fast_slow_diff(found, keys, titled(), analytics)
    )


def cost_to_go_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/cost-to-go`: the expected agent steps to a run's end from each
    skill-machine state (`flow.cost_to_go`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "cost_to_go", lambda found, _: cost_to_go(found, keys, titled(), analytics)
    )


#: What `/api/analytics/missed-loads` lists per skill, and `/api/analytics/trace-clusters` samples per cluster.
_LISTED = 5


#: `/api/analytics/trace-clusters`'s defaults: the cosine distance an average-linkage merge stops at, and the distinct
#: sessions a cluster needs to be reported.
_CLUSTER_THRESHOLD, _CLUSTER_MIN_SESSIONS = 0.8, 5


def _whole(query: dict[str, list[str]], key: str, default: int) -> int | None:
    """The whole number of at least 0 `key` gives, `default` when absent; None for anything else."""
    try:
        value = int(query[key][0]) if key in query else default
    except ValueError:
        return None
    return value if value >= 0 else None


def _case_ref(case: Case) -> dict[str, Any]:
    return {"harness": case.harness, "session": case.session, "task": case.task, "last_at": case.last_seen}


def _telemetry_cases(
    telemetry: TelemetryLog | None,
    window: float,
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    analytics: Analytics,
    now: float,
    kind: str,
    include_eval: bool = True,
) -> list[Case] | tuple[bytes, int]:
    """The cases of the signals from the last `window` hours, or the 501, 503 or (a window longer than the history)
    400 response for a log that has none. `include_eval` False leaves out the signals an eval run stamped."""
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot read what its sessions did"), 501
    found = _held_signals(telemetry, window, kind, now, "analytics")
    if isinstance(found, tuple):
        return found
    if not include_eval:
        found = [s for s in found if not s.eval]
    return trace_cases(found, keys, roots=analytics.roots, tasks=titled(), analytics=analytics)


def missed_loads_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    analytics: Analytics,
    now: float,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/missed-loads`: per declared skill (or the one named by `skill`), the
    cases of the last `hours` (default 168) that ran its trigger and those that did so without loading it, the `list`
    (default 5) newest of the latter listed. A window longer than the telemetry history is 400 with `history_s`."""
    window, listed = _hours(query, "hours", _HEALTH_HOURS), _whole(query, "list", _LISTED)
    if window is None or listed is None:
        return _error("hours must be a positive number and list a whole number"), 400
    found = _telemetry_cases(telemetry, window, keys, titled, analytics, now, "missed_loads")
    if isinstance(found, tuple):
        return found
    wanted = query.get("skill", [""])[0]
    skills = [
        {
            "skill": result.skill,
            "performed": len(result.performed),
            "missed": len(result.missed),
            "listed": [_case_ref(c) for c in sorted(result.missed, key=lambda c: -c.last_seen)[:listed]],
        }
        for result in missed_loads(found, [t for t in analytics.skill_loads if not wanted or t.skill == wanted])
    ]
    return encode("missed_loads", {"now": now, "window_s": window * 3600, "skills": skills}), 200


def _natural(task: str) -> tuple[str, int]:
    prefix, _, number = task.rpartition("-")
    return prefix, int(number) if number.isdigit() else 0


def _cluster_view(cluster: Cluster, analytics: Analytics, outliers: int) -> dict[str, Any]:
    cases = cluster.cases
    tasks = sorted({c.task for c in cases if c.task}, key=_natural)
    loaded = Counter(s for c in cases for s in set(c.skills) - analytics.lifecycle_skills)
    titles = Counter(c.title for c in cases if c.title)
    medoid, spread = None, []
    if outliers:
        found = dispersion(cluster, outliers, analytics.stop_activities)
        medoid = {
            "case": _case_ref(found.medoid),
            "median_distance": found.median,
            "trace": trace(found.medoid, analytics.stop_activities),
        }
        spread = [
            {
                "case": _case_ref(o.case),
                "distance": o.distance,
                "deletions": list(o.deletions),
                "insertions": list(o.insertions),
            }
            for o in found.outliers
        ]
    return {
        "key": cluster_key(cluster),
        "sessions": cluster.sessions,
        "cases": len(cases),
        "tasks": tasks,
        "first_at": min(c.last_seen for c in cases),
        "last_at": max(c.last_seen for c in cases),
        "kinds": dict(Counter(c.kind for c in cases)),
        "descriptors": list(cluster.descriptors),
        "skills": [{"skill": s, "cases": n} for s, n in sorted(loaded.items(), key=lambda i: (-i[1], i[0]))[:3]],
        "uncovered": sum(1 for c in cases if not set(c.skills) - analytics.lifecycle_skills),
        "sample_sessions": sorted({c.session for c in cases})[:_LISTED],
        "sample_tasks": tasks[:_LISTED],
        "titles": [t for t, _ in sorted(titles.items(), key=lambda i: (-i[1], i[0]))[:3]],
        "missed_loads": [
            {"skill": m.skill, "performed": len(m.performed), "missed": len(m.missed)}
            for m in missed_loads(cases, analytics.skill_loads)
            if m.missed
        ],
        "medoid": medoid,
        "outliers": spread,
    }


def trace_clusters_response(
    telemetry: TelemetryLog | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    analytics: Analytics,
    now: float,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/trace-clusters`: the trace clusters of the cases of the last `hours`
    (default 168) with `min_sessions` (default 5) or more distinct sessions, cut at cosine distance `threshold`
    (default 0.8, up to 2). `outliers` N adds each cluster's medoid and its N furthest cases; `new_hours` keeps only the
    clusters whose oldest case is that recent, clustering still running over every case in the window. A window longer than the telemetry history is 400 with
    `history_s`."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    new = _hours(query, "new_hours", 1) if "new_hours" in query else math.inf
    threshold = _hours(query, "threshold", _CLUSTER_THRESHOLD)
    sessions, outliers = _whole(query, "min_sessions", _CLUSTER_MIN_SESSIONS), _whole(query, "outliers", 0)
    if window is None or new is None or threshold is None or threshold > 2 or not sessions or outliers is None:
        return (
            _error(
                "hours and new_hours must be positive numbers, threshold one up to 2, min_sessions a whole number "
                "of 1 or more and outliers a whole number"
            ),
            400,
        )
    found = _telemetry_cases(telemetry, window, keys, titled, analytics, now, "trace_clusters", include_eval=False)
    if isinstance(found, tuple):
        return found
    clusters = trace_clusters(found, stop=analytics.stop_activities, threshold=threshold)
    shown = [
        c
        for c in clusters
        if c.sessions >= sessions and (new == math.inf or min(x.last_seen for x in c.cases) >= now - new * 3600)
    ]
    body = {
        "now": now,
        "window_s": window * 3600,
        "threshold": threshold,
        "min_sessions": sessions,
        "cases": sum(1 for c in found if c.tool_calls > 0),
        "clustered": sum(len(c.cases) for c in clusters),
        "clusters": [_cluster_view(c, analytics, outliers) for c in shown],
    }
    return encode("trace_clusters", body), 200
