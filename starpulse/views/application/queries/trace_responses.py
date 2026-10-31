"""The trace analytics routes' bodies and statuses: missed skill loads and trace clusters."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.flow_metrics.model.clusters import Cluster, cluster_key, dispersion, trace, trace_clusters
from starpulse.flow_metrics.model.traces import Case, missed_loads
from starpulse.flow_metrics.model.traces import cases as trace_cases
from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog
from starpulse.views.application.queries.responses import _HEALTH_HOURS, _error, _held_signals, _hours
from starpulse.views.model.encoding import encode

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
