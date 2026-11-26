"""The read routes' bodies and statuses: each takes the stores it reads and answers `(bytes, status)`."""

import logging
import math
import re
import time
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.board.model.ledger import PAGE
from starpulse.board.model.seam import (
    TaskReader,
)
from starpulse.flow_metrics.model.level_metrics import WindowPastHistory
from starpulse.flow_metrics.model.spend import task_spend
from starpulse.views.model.encoding import encode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.search import SearchIndex
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.views.ports.signal_folds import SignalFoldReader


#: The most rows a paged read serves at once.
PAGE_LIMIT = 100


def _error(message: str) -> bytes:
    return encode("error", {"error": message})


def _page_query(query: dict[str, list[str]], noun: str) -> tuple[float | None, int] | bytes:
    """The `before` and `limit` of a paged route, or the 400 body for one that is malformed."""
    try:
        before = float(query["before"][0]) if "before" in query else None
        limit = int(query["limit"][0]) if "limit" in query else PAGE
    except ValueError:
        return _error(f"{noun} takes a numeric ?before= and an integer ?limit=")
    if before is not None and not math.isfinite(before) or not 0 < limit <= PAGE_LIMIT:
        return _error(f"{noun} takes a finite ?before= and a ?limit= from 1 to {PAGE_LIMIT}")
    return before, limit


def done_response(feed: BoardFeed, read: TaskReader, query: dict[str, list[str]]) -> tuple[bytes, int]:
    """The body and status for `/api/done`: the next page of cold done tasks, each read from the board for its card."""
    asked = _page_query(query, "done")
    if isinstance(asked, bytes):
        return asked, 400
    stubs, more = feed.cold_page(*asked, query["milestone"][0] if "milestone" in query else None)
    tasks = []
    for stub in stubs:
        record = stub["record"] if "record" in stub else (read(stub["id"]) or {})
        tasks.append(_done_card(stub, record))
    return encode("done", {"tasks": tasks, "more": more}), 200


def _done_card(stub: dict, record: Mapping[str, Any]) -> dict:
    """A kanban card for a cold done task: its stub's id and entered time with the card fields of its board record."""
    card = {key: record[key] for key in ("labels", "milestone", "type", "follows") if key in record}
    named = {"id": stub["id"], "title": record.get("title") or stub["id"], "state": "done"}
    return named | {"model": record.get("profile") or "", "entered": stub["entered"]} | card


#: A GitHub pull request URL, which a task links to: its `owner/repo` and number.
_PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")


def _cited(links: list[str]) -> list[tuple[str, int]]:
    """The (repository, number) of each pull request page in `links`."""
    return [(match[1], int(match[2])) for match in map(_PULL_URL.fullmatch, links) if match]


def _without_bodies(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in record.items() if key != "body"} for record in records]


def cited_pulls(pulls: PullStore | None, links: list[str]) -> list[dict[str, Any]]:
    """The stored pull requests `links` name, without their bodies: each one's state and checks, so a task
    record shows them as the pull requests page does."""
    if not pulls:
        return []
    return _without_bodies(record for repo, number in _cited(links) for record in pulls.find(repo, number))


def task_pulls(pulls: PullStore | None, links: list[str]) -> list[dict[str, Any]]:
    """The stored pull requests `links` name, whole: each with its body and the paths it changes in `detail`."""
    if not pulls:
        return []
    return [record for repo, number in _cited(links) for record in pulls.find(repo, number, detailed=True, bodies=True)]


#: `/api/search`'s default and largest number of hits.
_SEARCH_HITS = 10


_SEARCH_LIMIT = 100


def search_response(
    search: SearchIndex | None,
    query: dict[str, list[str]],
    *,
    wait: bool = False,
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
    if (
        not words
        or not 0 < limit <= _SEARCH_LIMIT
        or (days is not None and days < 1)
        or ("before" in query and not before)
    ):
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


def _history_s(oldest: float | None, now: float) -> float:
    """The seconds of history the table holds as of `now`, `oldest` the time of its oldest signal (none: it holds none)."""
    return now - (now if oldest is None else oldest)


def spend_response(
    telemetry: SignalFoldReader | None,
    task: str,
    query: dict[str, list[str]],
    now: float,
) -> tuple[bytes, int]:
    """The body and status of `task`'s spend: its tokens by phase (`spend.task_spend`) over the last `hours`, from its
    sessions' `spend` fold rows, against its cell's peers; no telemetry is 501, and a database that cannot be read or a
    task_spend family being refolded 503.

    The oldest signal folded is where its history begins: a window that starts before it is 400 with the history's
    length (`history_s`), never answered with its missing hours as empty, as `level_response` refuses one."""
    window = _hours(query, "hours", _WINDOW_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if telemetry is None:
        return _error("this instance receives no harness telemetry, so it cannot report spend"), 501
    try:
        history = _history_s(telemetry.oldest(), now)
        if window * 3600 > history:
            return encode("spend", {"error": str(WindowPastHistory(window * 3600, history)), "history_s": history}), 400
        held = telemetry.task_spend(task, now - window * 3600)
    except Exception as exc:  # the event log's database is unreachable
        logger.warning("spend: signal table unreadable: %s", exc)
        return _error("the telemetry log cannot be read"), 503
    if held is None:
        return _error("the task spend is being refolded from the spend folds: ask again shortly"), 503
    folds, peers, tasks = held
    report = task_spend(folds, task, tasks, peers)
    return encode("spend", {"now": now, "window_s": window * 3600, "spend": report}), 200
