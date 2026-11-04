"""The read routes' bodies and statuses: each takes the stores it reads and answers `(bytes, status)`."""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.board.ledger import PAGE
from starpulse.board.model.seam import (
    TaskReader,
)
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.api.dto.health import SessionStep
from starpulse.flow_metrics.model import analytics
from starpulse.flow_metrics.model.cells import cell_report, combine_cost, estimate_report
from starpulse.flow_metrics.model.flow import combine_cost_to_go, combine_diff, combine_edges, combine_stages
from starpulse.flow_metrics.model.level_metrics import WindowPastHistory
from starpulse.flow_metrics.model.session_health import combine_health, slice_health
from starpulse.flow_metrics.model.spend import spend_report
from starpulse.flow_metrics.model.steps import combine_steps
from starpulse.machine_engine.model.stays import lane_stays
from starpulse.views.model.encoding import encode, encode_rows

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.search import SearchIndex
    from starpulse.board.board_feed import BoardFeed
    from starpulse.flow_metrics.adapters.outbound.history import History
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.views.ports.signal_folds import SignalFoldReader


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
        body["plan_revisions"] = history.plan_revisions(task)
    return encode("history", body), 200


def pulls_response(pulls: PullStore | None, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/pulls`: the stored pull requests matching every filter given; one named by both
    `repo` and `number` also carries `files`, the paths it changes (null for a record saved before they were kept).

    A `number` that is not an integer, or a `state` that is not open, merged or closed, is 400."""
    state = query.get("state", [""])[0].upper() or None
    try:
        number = int(query["number"][0]) if "number" in query else None
    except ValueError:
        return _error("pulls takes an integer ?number="), 400
    if state not in (None, "OPEN", "MERGED", "CLOSED"):
        return _error("pulls takes ?state= open, merged or closed"), 400
    repo = query.get("repo", [""])[0] or None
    one = repo is not None and number is not None
    found = pulls.find(repo, number, state, query.get("body_contains", [""])[0] or None, detailed=one) if pulls else []
    if one:  # one pull request is read whole: its changed files, which a listing leaves out
        found = [
            {**{key: value for key, value in record.items() if key != "detail"}, "files": (record["detail"] or {}).get("files")}
            for record in found
        ]
    return encode("pulls", {"pulls": found}), 200


#: A GitHub pull request URL, which a task cites in its references: its `owner/repo` and number.
_PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")


def _cited(references: list[str]) -> list[tuple[str, int]]:
    """The (repository, number) of each pull request `references` cites."""
    return [(match[1], int(match[2])) for match in map(_PULL_URL.fullmatch, references) if match]


def _without_bodies(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in record.items() if key != "body"} for record in records]


def cited_pulls(pulls: PullStore | None, references: list[str]) -> list[dict[str, Any]]:
    """The stored pull requests `references` cite, without their bodies: each one's state and checks, so a task
    record shows them as the pull requests page does."""
    if not pulls:
        return []
    return _without_bodies(record for repo, number in _cited(references) for record in pulls.find(repo, number))


def resident_pulls(pulls: PullStore | None, references: list[str]) -> list[dict[str, Any]] | None:
    """`cited_pulls` when memory holds what every cited pull request answers, so no query runs; None when only the
    database can say."""
    if not pulls:
        return []
    held = [pulls.resident(repo, number) for repo, number in _cited(references)]
    if any(records is None for records in held):
        return None
    return _without_bodies(record for records in held for record in records or [])


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
    from starpulse.flow_metrics.adapters.outbound.history import HealthHistory, SummarisedHealth  # noqa: PLC0415 - the database stack loads when a store does

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


def refuses_at_once(telemetry: SignalFoldReader | None, query: dict[str, list[str]], now: float, span: int = 1) -> bool:
    """Whether a telemetry report of the last `span` x `hours` answers with a refusal that needs no fold: an `hours`
    that is no positive number, no telemetry, or a window longer than the history (`_held_folds`)."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None or telemetry is None:
        return True
    try:
        oldest = telemetry.oldest()
    except Exception:  # the event log's database is unreachable: the fold answers 503
        return False
    return window * span * 3600 > _history_s(oldest, now)


def _history_s(oldest: float | None, now: float) -> float:
    """The seconds of history the table holds as of `now`, `oldest` the time of its oldest signal (none: it holds none)."""
    return now - (now if oldest is None else oldest)


#: The views each kind-and-size route combines; a route reads no other view's rows.
_ROUTE_VIEWS = {
    "transitions": ("cost",),
    "cells": ("health",),
    "estimates": ("health",),
    "graph": ("runs",),
    "stages": ("runs",),
    "diff": ("runs", "health"),
    "cost_to_go": ("runs", "health"),
}


def _held_folds(
    telemetry: SignalFoldReader, window: float, kind: str, now: float, label: str, views: tuple[str, ...] = ()
) -> dict[str, list[Any]] | tuple[bytes, int]:
    """The per-session fold results of the `views` for the last `window` hours as of `now`, or the 503 response for a
    database that cannot be read.

    The oldest signal the table holds is where its history begins: a window that starts before it is 400 with the
    history's length (`history_s`), never answered with its missing hours as empty, as `level_response` refuses one."""
    try:
        oldest = telemetry.oldest()
        history = _history_s(oldest, now)
        held = None if window * 3600 > history else telemetry.window(now - window * 3600, views)
    except Exception as exc:  # the event log's database is unreachable
        logger.warning("%s: signal table unreadable: %s", label, exc)
        return _error("the telemetry log cannot be read"), 503
    if held is None:
        return encode(kind, {"error": str(WindowPastHistory(window * 3600, history)), "history_s": history}), 400
    return held


def sessions_response(
    telemetry: SignalFoldReader | None,
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
    held = _held_folds(telemetry, window, "sessions", now, "sessions", ("health",))
    if isinstance(held, tuple):
        return held
    rows = combine_health(held["health"])
    body = {"now": now, "window_s": window * 3600, "sessions": rows, "slices": slice_health(rows)}
    return encode("sessions", body), 200


def steps_response(
    telemetry: SignalFoldReader | None,
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
    held = _held_folds(telemetry, window, "session_steps", now, "steps", ("steps",))
    if isinstance(held, tuple):
        return held
    rows = (((row["at"], row["harness"], row["session"]), row) for row in combine_steps(held["steps"]))
    head = {"now": now, "window_s": window * 3600}
    return encode_rows("session_steps", head, "steps", SessionStep, rows), 200


def _kind_size_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    now: float,
    label: str,
    report: Callable[[dict[str, list[Any]], float], list[dict[str, Any]]],
    span: int = 1,
) -> tuple[bytes, int]:
    """The body and status for a report by kind and size of the signals from the last `span` x `hours` (default 168
    each) as of `now`, keyed `label`: `{now, window_s, <label>: report(folds, since)}`, `since` the start of the
    last `hours`. An instance that receives no harness telemetry is 501, a log that cannot be read 503, and a window
    longer than the telemetry history 400 with `history_s`."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error(f"this instance receives no harness telemetry, so it cannot report {label}"), 501
    held = _held_folds(telemetry, window * span, label, now, label, _ROUTE_VIEWS[label])
    if isinstance(held, tuple):
        return held
    return encode(label, {"now": now, "window_s": window * 3600, label: report(held, now - window * 3600)}), 200


def transitions_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/transitions`: the cost of each skill within each kind and size
    (`cells.transition_cost`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "transitions", lambda held, _: combine_cost(held["cost"], titled())
    )


def spend_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/spend`: each task's tokens by phase (`spend.spend_report`) over the
    last `hours`, read from the window's sessions; refusals as `steps_response`."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot report spend"), 501
    held = _held_folds(telemetry, window, "spend", now, "spend")
    if isinstance(held, tuple):
        return held
    found = [signal for group in telemetry.sessions(now - window * 3600) for signal in group]
    report = spend_report(found, keys, titled(), analytics)
    return encode("spend", {"now": now, "window_s": window * 3600, "spend": report}), 200


def cells_response(
    telemetry: SignalFoldReader | None,
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
        lambda held, _: cell_report(slice_health(combine_health(held["health"])), titled()),
    )


def estimates_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/estimates`: each completed task's size estimate beside its measured
    steps, active minutes and effort size step (`estimates.estimate_report`) over the last `hours`, only the tasks of
    `milestone` when given; refusals as `steps_response`."""
    milestone = next(iter(query.get("milestone", [])), None)
    bands = analytics.size_bands if analytics is not None else ()
    return _kind_size_response(
        telemetry,
        query,
        now,
        "estimates",
        lambda held, _: estimate_report(
            slice_health(combine_health(held["health"])), titled(), bands, milestone
        ),
    )


def graph_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/graph`: the branching directly-follows graph of each transition
    (`flow.directly_follows`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "graph", lambda held, _: combine_edges(held["runs"], titled(), analytics)
    )


def stages_response(
    telemetry: SignalFoldReader | None,
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
        lambda held, since: combine_stages(held["runs"], titled(), analytics, since=since),
        span=2,
    )


def diff_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/diff`: each transition's reference run against its slowest clean run
    (`flow.fast_slow_diff`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "diff", lambda held, _: combine_diff(held["runs"], combine_health(held["health"]), titled(), analytics)
    )


def cost_to_go_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/cost-to-go`: the expected agent steps to a run's end from each
    skill-machine state (`flow.cost_to_go`) over the last `hours`; refusals as `steps_response`."""
    return _kind_size_response(
        telemetry, query, now, "cost_to_go", lambda held, _: combine_cost_to_go(held["runs"], combine_health(held["health"]), titled(), analytics)
    )
