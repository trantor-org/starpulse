"""`/api/search`: hits and results."""

from __future__ import annotations

from starpulse.contracts.api._base import _Api


class SearchHit(_Api):
    """One task a search found: where it is now, and the text around the match."""

    task: str
    title: str
    lane: str
    score: float
    snippet: str


class SearchResults(_Api):
    """`GET /api/search?q=&limit=&label=&finished_within_days=`: the tasks holding every word of `q`, best match first,
    each carrying every `label` and, with `finished_within_days`, open or finished within that many days."""

    query: str
    hits: list[SearchHit]
