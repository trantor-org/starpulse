"""The duplicate search a create runs: the tasks its queries, its citations and its meaning bring up, recorded as the
task's `duplicate_search` for the board's `names_ids` guard to hold the creator's resolution to."""

import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

from starpulse.board.adapters.search import EmbeddingError, SearchIndex
from starpulse.machine_engine.model.state_roles import StateRoles

__all__ = ["Duplicates", "Linked", "duplicate_search"]

_TEXT_HITS = 10
_MAX_HITS = 100
_NEAREST = 20
_SEMANTIC_KEEP = 3
_OPEN_KEEP = 3
_ASKS = 3
#: The days a finished task still counts as a candidate, and the days of the narrower window that lets an open task or
#: one finished today outrank the finished ones the wide window is crowded with.
_FINISHED_DAYS = 30
_OPEN_DAYS = 1
_CHARS = 2000
_CITATION = re.compile(r"\bTASK-(\d+(?:\.\d+)*)\b|(?:(?<![\w&])#|/pull/)(\d+)\b", re.IGNORECASE)
_ARCHIVED = "archived"


class Linked(Exception):
    """A scheduled create (one with a `source`) whose work an open task already carries."""


class Duplicates(NamedTuple):
    """What a create's duplicate search needs: the search index, the board's roles and its task reader."""

    search: SearchIndex
    roles: StateRoles
    read: Callable[[str], dict[str, Any] | None]


def _citations(text: str) -> set[str]:
    return {f"TASK-{task}" if task else f"#{pull}" for task, pull in _CITATION.findall(text)}


def _days(days: int) -> float:
    return time.time() - days * 86400


def _hits(
    found: Duplicates, query: str, limit: int, days: int | None = None, *, similar: bool = False
) -> list[dict[str, Any]]:
    since = None if days is None else _days(days)
    return found.search.search(" ".join(query.split()), limit, finished_since=since, wait=similar)


def _nearest(found: Duplicates, query: str, days: int) -> list[dict[str, Any]]:
    # A query whose embedding times out ranks by words and can answer nothing under load: ask again.
    for _ in range(_ASKS):
        if hits := _hits(found, query, _MAX_HITS, days, similar=True):
            break
    return hits


def _candidate(hit: dict[str, Any]) -> dict[str, str]:
    return {"task": str(hit["task"]), "title": str(hit["title"]), "status": str(hit["lane"])}


def _terminal(found: Duplicates, candidate: dict[str, str]) -> bool:
    """Whether a candidate is finished work: its lane is none the board's machine leaves open. A status spelled as a
    task file does (`In Progress`) is read as its lane id."""
    opened = {found.roles.initial, *found.roles.lanes}
    return candidate["status"].lower().replace(" ", "_") not in opened


def _description(found: Duplicates, task: str) -> str | None:
    record = found.read(task)
    return str((record or {}).get("description") or "").strip() or None


def _cited(found: Duplicates, text: str) -> list[dict[str, str]]:
    """The open tasks that duplicate `text`, whose first line is the new title: same title, and the description cites a
    task or pull request `text` cites. A shared citation alone is no duplicate, since slices of one spec share them."""
    cites = _citations(text)
    title = tuple(text.split("\n", 1)[0].casefold().split())
    hits: dict[str, dict[str, str]] = {}
    for cite in sorted(cites):
        for hit in _hits(found, cite, _MAX_HITS):
            if tuple(str(hit["title"]).casefold().split()) == title:
                hits.setdefault(str(hit["task"]), _candidate(hit))
    opened = [hit for hit in hits.values() if not _terminal(found, hit)]
    with ThreadPoolExecutor() as readers:
        bodies = list(readers.map(lambda hit: _description(found, hit["task"]), opened))
    cited = [hit for hit, body in zip(opened, bodies, strict=True) if body and _citations(body) & cites]
    return sorted(cited, key=lambda hit: hit["task"])


def _semantic(found: Duplicates, text: str) -> list[dict[str, str]]:
    """The tasks the reranker ranks highest among the nearest hits for `text`, and the nearest open hits it may have
    scored low or the pool cut."""
    nearest: dict[str, dict[str, Any]] = {}
    hits: list[dict[str, Any]] = []
    for days in (_FINISHED_DAYS, _OPEN_DAYS):
        hits = _nearest(found, text[:_CHARS], days)
        for hit in hits[:_NEAREST]:
            nearest.setdefault(str(hit["task"]), hit)
    pool = list(nearest.values())
    if not pool:
        return []
    with ThreadPoolExecutor() as readers:
        bodies = list(
            readers.map(
                lambda hit: None if str(hit["lane"]).casefold() == _ARCHIVED else _description(found, str(hit["task"])),
                pool,
            )
        )
    documents = [f"{hit['title']}\n{body or hit['snippet']}"[:_CHARS] for hit, body in zip(pool, bodies, strict=True)]
    scores = found.search.rerank(text[:_CHARS], documents)
    ranked = pool if scores is None else [hit for _, hit in sorted(zip(scores, pool, strict=True), key=lambda pair: -pair[0])]
    kept = [_candidate(hit) for hit in ranked[:_SEMANTIC_KEEP]]
    nearest_open = [item for item in map(_candidate, hits) if not _terminal(found, item)][:_OPEN_KEEP]
    return kept + [item for item in nearest_open if item not in kept]


def _masked(text: str) -> str:
    """`text` with each task id read as plain words (`TASK-5` as `task 5`): the guard reads a bare id in the record as an
    open candidate the resolution must name, so free text there names none."""
    return re.sub(r"\bTASK-(?=\d)", "task ", text, flags=re.IGNORECASE)


def _listed(candidates: list[dict[str, str]]) -> str:
    return ", ".join(f"{item['task']} ({item['status']})" for item in candidates)


def duplicate_search(
    found: Duplicates, queries: list[str], text: str, *, source: str = ""
) -> tuple[str, list[dict[str, str]]]:
    """The `duplicate_search` record for a create of `text` and the candidates it lists, from the creator's `queries`, the
    open tasks citing what `text` cites and the tasks nearest its meaning.

    Each leg considers the open tasks and those finished in the last 30 days; each query also searches the open tasks
    and those finished today. A failed embedder or reranker leaves the full-text candidates and names the failure in
    the record. A create of a `source` whose work an open task already cites raises `Linked`, naming that task.
    """
    candidates: dict[str, dict[str, str]] = {}
    for query in filter(str.strip, queries):
        for days in (_FINISHED_DAYS, _OPEN_DAYS):
            for hit in _hits(found, query, _TEXT_HITS, days):
                candidates.setdefault(str(hit["task"]), _candidate(hit))
    cited = _cited(found, text)
    if source and cited:
        raise Linked(f"{cited[0]['task']}: {cited[0]['title']}")
    error = ""
    nearest: list[dict[str, str]] = []
    if text.strip() and not source:
        try:
            nearest = _semantic(found, text)
        except EmbeddingError as exc:
            error = _masked(f"{type(exc).__name__}: {exc}")
    for item in [*cited, *nearest]:
        candidates.setdefault(item["task"], item)
    ordered = sorted(candidates.values(), key=lambda item: item["task"])
    terminal = [item for item in ordered if _terminal(found, item)]
    opened = [item for item in ordered if not _terminal(found, item)]
    head = "; ".join(_masked(query.strip()) for query in queries if query.strip())
    if source:
        head = head or f"Source `{source}`: no open task on the board carries it."
    parts = [head]
    if terminal:
        parts.append(f"Terminal candidates: {_listed(terminal)}")
    if opened:
        parts.append(f"Open candidates: {_listed(opened)}")
    if error:
        parts.append(f"Semantic candidates unavailable, so full-text search alone ran: {error}")
    return "\n\n".join(parts), opened
