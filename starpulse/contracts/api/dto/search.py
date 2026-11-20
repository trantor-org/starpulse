"""`/api/search`: hits and results."""

from starpulse.contracts.api._base import _Api


class SearchHit(_Api):
    """One task a search found: where it is now, and the text around the match."""

    task: str
    title: str
    lane: str
    score: float
    snippet: str
    field: str = ""


class SearchResults(_Api):
    """`GET /api/search?q=&limit=&label=&finished_within_days=&before=`: the tasks holding every word of `q`, best
    match first, each carrying every `label`, with `finished_within_days` open or finished within that many days, and
    with `before` (a task key) of its prefix and created before it. `GET /api/search/similar` takes the same query and
    answers the same body, waiting to embed a query it holds no vector for."""

    query: str
    hits: list[SearchHit]
