"""The read routes' bodies and statuses: each takes the stores it reads and answers `(bytes, status)`."""

import json
import logging
import math
import re
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.board.model.ledger import PAGE
from starpulse.board.model.seam import (
    TaskReader,
)
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.flow_metrics.model.level_metrics import WindowPastHistory
from starpulse.flow_metrics.model.spend import combine_spend
from starpulse.views.model.encoding import encode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.search import SearchIndex
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.views.ports.signal_folds import SignalFoldReader


#: The most rows `/api/ledger/<event>` serves at once.
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


def done_response(feed: BoardFeed, read: TaskReader, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/done`: the next page of cold done tasks, each read from the board for its card."""
    asked = _page_query(query, "done")
    if isinstance(asked, bytes):
        return asked, 400
    stubs, more = feed.cold_page(*asked)
    tasks = []
    for stub in stubs:
        record = stub["record"] if "record" in stub else (read(stub["id"]) or {})
        tasks.append(_done_card(stub, record))
    return encode("done", {"tasks": tasks, "more": more}), 200


def _done_card(stub: dict, record: Mapping[str, Any]) -> dict:
    """A kanban card for a cold done task: its stub's id and entered time with the card fields of its board record."""
    card = {key: record[key] for key in ("labels", "milestone", "type") if key in record}
    named = {"id": stub["id"], "title": record.get("title") or stub["id"], "state": "done"}
    return named | {"model": record.get("profile") or "", "entered": stub["entered"]} | card


def history_response(
    history: HistoryStore,
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


def pulls_response(
    pulls: PullStore | None, query: dict[str, list[str]], cited: Callable[[str], list[str]] | None = None
) -> tuple[bytes, int]:
    """The body and status for `/api/pulls`: the stored pull requests matching every filter given, without their
    bodies unless `bodies=1` asks or one is named by both `repo` and `number`, which also carries `files`, the paths it
    changes (null for a record saved before they were kept). `task` names the pull requests that task cites (`cited`
    gives its links), each read by its key.

    A `number` that is not an integer, or a `state` that is not open, merged or closed, is 400."""
    state = query.get("state", [""])[0].upper() or None
    try:
        number = int(query["number"][0]) if "number" in query else None
    except ValueError:
        return _error("pulls takes an integer ?number="), 400
    if state not in (None, "OPEN", "MERGED", "CLOSED"):
        return _error("pulls takes ?state= open, merged or closed"), 400
    repo = query.get("repo", [""])[0] or None
    task = query.get("task", [""])[0]
    one = repo is not None and number is not None and not task
    bodies = one or query.get("bodies", [""])[0] in ("1", "true")
    needle = query.get("body_contains", [""])[0] or None
    if not pulls:
        found = []
    elif task:
        links = cited(task) if cited else []
        found = [
            record
            for named, held in _cited(links)
            if repo in (None, named) and number in (None, held)
            for record in pulls.find(named, held, state, needle, bodies=bodies)
        ]
    else:
        found = pulls.find(repo, number, state, needle, detailed=one, bodies=bodies)
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


#: `/api/search`'s default and largest number of hits.
_SEARCH_HITS = 10


_SEARCH_LIMIT = 100


def search_response(
    search: SearchIndex | None, query: dict[str, list[str]], *, wait: bool = False
) -> tuple[bytes, int]:
    """The body and status for `/api/search`: the tasks holding every word of `?q=`, best first, at most `?limit=`;
    each repeated `?label=` keeps only the tasks carrying it, and `?finished_within_days=` drops a task that finished
    (settled, or entered the done lane) longer ago than that many days; `?before=` (a task key) keeps only the tasks of
    its prefix created before it, before `limit` cuts. `wait` is `/api/search/similar`: it embeds a query it holds no
    vector for before it answers, where `/api/search` answers by words at once and embeds in the background.

    A server with no index is 404; a blank `q`, a `limit` that is not an integer from 1 to 100, a
    `finished_within_days` that is not a positive integer or a `before` that is no task key is 400."""
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
    prefix, _, number = query["before"][0].rpartition("-") if "before" in query else ("", "", "")
    before = (prefix, int(number)) if prefix and number.isdecimal() else None
    if not words or not 0 < limit <= _SEARCH_LIMIT or (days is not None and days < 1) or ("before" in query and not before):
        return _error(
            f"search takes a ?q= of words, a ?limit= from 1 to {_SEARCH_LIMIT}, a positive ?finished_within_days= "
            "and a task key ?before="
        ), 400
    since = None if days is None else time.time() - days * 86400
    hits = search.search(words, limit, labels=query.get("label", []), finished_since=since, before=before, wait=wait)
    return encode("search", {"query": words, "hits": hits}), 200


#: The window the per-task reads default to, in hours.
_WINDOW_HOURS = 168.0


def _hours(query: dict[str, list[str]], key: str, default: float) -> float | None:
    """The positive, finite number of hours `key` gives, `default` when absent; None for anything else."""
    try:
        hours = float(query[key][0]) if key in query else default
    except ValueError:
        return None
    return hours if 0 < hours < float("inf") else None


def refuses_at_once(telemetry: SignalFoldReader | None, query: dict[str, list[str]], now: float) -> bool:
    """Whether a telemetry report of the last `hours` answers with a refusal that needs no fold: an `hours`
    that is no positive number, no telemetry, or a window longer than the history (`_held_folds`)."""
    window = _hours(query, "hours", _WINDOW_HOURS)
    if window is None or telemetry is None:
        return True
    try:
        oldest = telemetry.oldest()
    except Exception:  # the event log's database is unreachable: the fold answers 503
        return False
    return window * 3600 > _history_s(oldest, now)


def _history_s(oldest: float | None, now: float) -> float:
    """The seconds of history the table holds as of `now`, `oldest` the time of its oldest signal (none: it holds none)."""
    return now - (now if oldest is None else oldest)


def _held_folds(
    telemetry: SignalFoldReader,
    window: float,
    kind: str,
    now: float,
    label: str,
    views: tuple[str, ...] = (),
) -> dict[str, list[Any]] | tuple[bytes, int]:
    """The per-session fold results of the `views` for the last `window` hours as of `now`, or the 503 response for a
    database that cannot be read.

    The oldest signal folded is where its history begins: a window that starts before it is 400 with the
    history's length (`history_s`), never answered with its missing hours as empty, as `level_response` refuses one."""
    try:
        oldest = telemetry.oldest()
        history = _history_s(oldest, now)
        since = now - window * 3600
        held = None if window * 3600 > history else telemetry.window(since, views)
    except Exception as exc:  # the event log's database is unreachable
        logger.warning("%s: signal table unreadable: %s", label, exc)
        return _error("the telemetry log cannot be read"), 503
    if held is None:
        return encode(kind, {"error": str(WindowPastHistory(window * 3600, history)), "history_s": history}), 400
    return held


def spend_response(
    telemetry: SignalFoldReader | None,
    query: dict[str, list[str]],
    keys: TaskKeys | None,
    titled: Callable[[], Mapping[str, Mapping[str, Any]]],
    now: float,
    analytics: Analytics | None = None,
) -> tuple[bytes, int]:
    """The body and status for `spend_response`: each task's tokens by phase (`spend.spend_report`) over the
    last `hours`, combined from the window's `spend` fold rows; a window longer than the history is 400, no telemetry 501."""
    window = _hours(query, "hours", _WINDOW_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot report spend"), 501
    held = _held_folds(telemetry, window, "spend", now, "spend", ("spend",))
    if isinstance(held, tuple):
        return held
    report = combine_spend(sorted(held["spend"], key=lambda fold: (fold["harness"], fold["session"])), titled())
    return encode("spend", {"now": now, "window_s": window * 3600, "spend": report}), 200


def task_spend_response(week: tuple[bytes, int], task: str) -> tuple[bytes, int]:
    """The body and status for `/api/task-spend/<task>`: the task's phases of the `week` answer `spend_response`
    gave, none for a task that spent nothing in the window; a refusal passes through."""
    body, status = week
    if status != 200:
        return week
    report = json.loads(body)
    rows = [row for row in report["spend"] if row["task"] == task]
    return encode("taskSpend", {"task": task, "now": report["now"], "window_s": report["window_s"], "spend": rows}), 200
