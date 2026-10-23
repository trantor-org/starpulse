"""Full-text search over the board's tasks, kept in the instance's own database.

The index is an SQLite FTS5 table of each placed task's id, title, description, acceptance criteria and notes. It lives
beside the event log on the instance. A row is keyed by a
rowid derived from the task id, so replacing a task and reading its stored digest are point lookups, and a task placed
again unchanged, as every task is on a restart, writes nothing.

With an embeddings endpoint configured (`[search] embeddings_url`) the index also keeps one vector per task and model,
of the task's title and description, in a table beside the FTS5 one, and ranks a query's lexical hits by a blend of
their bm25 score and the cosine similarity between the query's vector and theirs. Embedding never runs on the feed's path: `index` writes the FTS5 row
and `embed_pending` (run by `keep_embedding`) catches the vectors up. Without an endpoint nothing calls out, and an
endpoint that fails leaves the lexical order.
"""

from __future__ import annotations

import array
import dataclasses
import hashlib
import http.client
import json
import logging
import math
import os
import threading
import time
import urllib.request
from collections.abc import Sequence

import numpy as np
from sqlalchemy import Connection, Engine, bindparam, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from starpulse._internal.config.search import Search
from starpulse.contracts.adapters import BoardTask

logger = logging.getLogger(__name__)

_TABLE = "starpulse_task_search"
_CREATE = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING fts5("
    "task, title, description, criteria, notes, lane UNINDEXED, digest UNINDEXED, tokenize = 'porter unicode61')"
)
#: What a match in each column is worth, in the column order above: a title says most, a note least.
_WEIGHTS = "4, 10, 2, 1, 1, 0, 0"
_SNIPPET_CHARS = 160
#: The lexical query: MATCH first into a MATERIALIZED CTE, then `{filtered}` (facets) on those rowids. ANDing the
#: facets IN onto MATCH makes SQLite look up each facet rowid in FTS (`0:=M`) and cost grows with rows × words.
_SEARCH = (
    f"WITH matched AS MATERIALIZED ("
    f"SELECT {_TABLE}.rowid AS row, task, title, lane, -bm25({_TABLE}, {_WEIGHTS}) AS score, "
    f"snippet({_TABLE}, -1, '', '', '…', 16) AS snippet, bm25({_TABLE}, {_WEIGHTS}) AS rank "
    f"FROM {_TABLE} WHERE {_TABLE} MATCH :query"
    f") SELECT task, title, lane, score, snippet FROM matched WHERE 1{{filtered}} "
    f"ORDER BY rank, task LIMIT :limit"
)
_DIGEST = text(f"SELECT digest FROM {_TABLE} WHERE rowid = :row")
_DELETE = text(f"DELETE FROM {_TABLE} WHERE rowid = :row")
_VECTORS = "starpulse_task_vectors"
_CREATE_VECTORS = (
    f"CREATE TABLE IF NOT EXISTS {_VECTORS} ("
    "task_row INTEGER NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL, PRIMARY KEY (task_row, model))"
)
_DROP_VECTORS = text(f"DELETE FROM {_VECTORS} WHERE task_row = :row")
#: What a search may filter a task by, a row per task: its labels, each on its own line so a label matches whole, and
#: when it finished (settled, or entered the done lane), NULL while it is open. A table of its own, so an index written
#: before it gains a task's row from the next `index` without the task's text, and so its vector, being written again.
_FACETS = "starpulse_task_facets"
_CREATE_FACETS = (
    f"CREATE TABLE IF NOT EXISTS {_FACETS} (task_row INTEGER PRIMARY KEY, labels TEXT NOT NULL, finished_at REAL)"
)
_HELD_FACETS = text(f"SELECT labels, finished_at FROM {_FACETS} WHERE task_row = :row")
_STORE_FACETS = text(
    f"INSERT OR REPLACE INTO {_FACETS} (task_row, labels, finished_at) VALUES (:row, :labels, :finished_at)"
)
_DROP_FACETS = text(f"DELETE FROM {_FACETS} WHERE task_row = :row")
#: Drops the vectors another recipe made, which no query reads.
_DROP_OTHER_RECIPES = text(f"DELETE FROM {_VECTORS} WHERE model != :model")
#: The text a task is embedded as, which keys its vector with the model: the title and Description, as the query is a
#: task-like sentence, and changing it makes every vector again.
_EMBEDDED_TEXT = "title+description"
_RANKED = (
    f"WITH matched AS MATERIALIZED ("
    f"SELECT {_TABLE}.rowid AS row, task, title, lane, -bm25({_TABLE}, {_WEIGHTS}) AS score, "
    f"snippet({_TABLE}, -1, '', '', '…', 16) AS snippet, bm25({_TABLE}, {_WEIGHTS}) AS rank, "
    f"{_VECTORS}.vector AS vector FROM {_TABLE} LEFT JOIN {_VECTORS} "
    f"ON {_VECTORS}.task_row = {_TABLE}.rowid AND {_VECTORS}.model = :model "
    f"WHERE {_TABLE} MATCH :query"
    f") SELECT task, title, lane, score, snippet, vector FROM matched WHERE 1{{filtered}} "
    f"ORDER BY rank, task LIMIT :limit"
)
#: Every embedded task, for a query whose meaning (not its words) is what is wanted; `snippet` is the task's opening.
_EMBEDDED_SELECT = (
    f"SELECT {_TABLE}.rowid AS row, task, title, lane, substr(description, 1, {_SNIPPET_CHARS}) AS snippet, "
    f"{_VECTORS}.vector AS vector FROM {_TABLE} JOIN {_VECTORS} "
    f"ON {_VECTORS}.task_row = {_TABLE}.rowid AND {_VECTORS}.model = :model"
)
_EMBEDDED = text(_EMBEDDED_SELECT)
#: Only the named rows of `_EMBEDDED`, which is how the held vectors catch up with the writes made since.
_EMBEDDED_ROWS = text(f"{_EMBEDDED_SELECT} WHERE {_TABLE}.rowid IN :rows").bindparams(bindparam("rows", expanding=True))
_PENDING = text(
    f"SELECT rowid AS row, title, description, digest FROM {_TABLE} "
    f"WHERE rowid NOT IN (SELECT task_row FROM {_VECTORS} WHERE model = :model) LIMIT :limit"
)
#: Stores a vector only for the text it was made from: a task replaced since is left for the next pass.
_STORE = text(
    f"INSERT OR REPLACE INTO {_VECTORS} (task_row, model, vector) SELECT :row, :model, :vector "
    f"WHERE (SELECT digest FROM {_TABLE} WHERE rowid = :row) = :digest"
)
#: How much of the lexical rank (the rest is the vector's cosine similarity) a hit keeps when a query is embedded.
_LEXICAL_WEIGHT = 0.5
#: The least cosine similarity at which a task that holds none of the query's words is still a hit: under
#: mxbai-embed-large a reworded task's original scores about 0.6 and an unrelated task 0.53 at most.
_RECALL_FLOOR = 0.55
#: How many lexical hits a ranked query blends before it cuts to `limit`, so a near meaning can rise past the top.
_POOL = 50
#: Tasks sent to the endpoint in one request, and the characters of one task's text it is sent. One, because the
#: endpoint embeds one request at a time: a query arriving behind a batch waits for all of it (2 s behind five texts on
#: a loaded host, 7 s behind 32), and behind one text it waits for that text alone.
_BATCH = 1
#: Rows changed since the held vectors were read beyond which reading them all again is cheaper than naming them.
_RELOAD_AT = 500
#: Seconds a held read of the vectors is trusted: `starpulse worker search` writes vectors this process never sees as
#: a write, so an older read is made again.
_SHARED_REFRESH_S = 30.0
_TEXT_LIMIT = 8000
_TIMEOUT = 10.0
#: Seconds a search waits for its query's vector before ranking lexically, so a slow endpoint costs the order and not
#: the answer.
_QUERY_TIMEOUT = 1.0
#: Seconds `keep_embedding` waits between passes, and after a failed one.
_POLL = 5.0
_RETRY = 60.0
_INSERT = text(
    f"INSERT INTO {_TABLE} (rowid, task, title, description, criteria, notes, lane, digest) "
    "VALUES (:row, :task, :title, :description, :criteria, :notes, :lane, :digest)"
)


def _filtered(labels: Sequence[str], finished_since: float | None, *, row: str = f"{_TABLE}.rowid") -> tuple[str, dict]:
    """The condition, ANDed onto a query's WHERE, that keeps the tasks carrying every one of `labels` and not finished
    before `finished_since` (epoch seconds), with its parameters; no condition when neither narrows.

    `row` is the outer column compared to `task_row` (the MATCH CTE's `row`, or `{_TABLE}.rowid` for a facets-only
    select)."""
    conditions = [f"instr(labels, :label_{at}) > 0" for at in range(len(labels))]
    parameters: dict = {f"label_{at}": f"\n{label}\n" for at, label in enumerate(labels)}
    if finished_since is not None:
        conditions.append("(finished_at IS NULL OR finished_at >= :finished_since)")
        parameters["finished_since"] = finished_since
    if not conditions:
        return "", {}
    return f" AND {row} IN (SELECT task_row FROM {_FACETS} WHERE {' AND '.join(conditions)})", parameters


def _row(task_id: str) -> int:
    """The index's rowid for a task: 56 bits of its id's hash, so a collision between two tasks of a board is a
    one-in-ten-billion event."""
    return int.from_bytes(hashlib.blake2b(task_id.encode(), digest_size=7).digest(), "big")


def _unit(vectors: np.ndarray) -> np.ndarray:
    """`vectors` (one, or one per row) scaled to length 1; a zero vector stays zero, which makes every similarity to it
    0."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


def _cosine(left: array.array, right: array.array) -> float:
    """The cosine similarity of two vectors; 0 for vectors of different lengths or a zero vector. `math.sumprod` runs
    each sum in C, as a Python loop over a thousand floats held the GIL against every other request thread."""
    norm = math.sqrt(math.sumprod(left, left) * math.sumprod(right, right))
    if len(left) != len(right) or not norm:
        return 0.0
    return math.sumprod(left, right) / norm


def _match(query: str) -> str:
    """`query` as an FTS5 expression of quoted words, all of which a task must hold, so its punctuation is text and
    never FTS5 syntax (`PROJ-45`, `NEAR`, `title:`)."""
    return " ".join('"' + word.replace('"', '""') + '"' for word in query.split())


@dataclasses.dataclass(frozen=True)
class _Near:
    """The embedded tasks a query is scored against: each task's rowid and `_EMBEDDED` row, and its unit vector as a
    row of `matrix`, so one product scores them all. Replaced whole, never changed in place, so a search holding one is
    unaffected by the next refresh."""

    rows: list[int]
    hits: list[dict]
    matrix: np.ndarray


class EmbeddingError(RuntimeError):
    """The embeddings endpoint did not answer with a vector for every text it was sent."""


class SearchIndex:
    """An FTS5 index of each placed task's id, title, description, acceptance criteria and notes."""

    def __init__(self, engine: Engine, settings: Search | None = None) -> None:
        self._engine = engine
        self._lock = threading.Lock()
        #: The embedded tasks' unit vectors, read once. A write that changes a task's vector adds its row to `_dirty`
        #: and the next search reads those rows alone, so a burst of writes never makes a search read every vector.
        self._near: _Near | None = None
        self._dirty: set[int] = set()
        self._read_at = 0.0
        #: Held by the one search refreshing `_near`, which reads and normalises outside `_lock` so a write never waits
        #: for it.
        self._refreshing = threading.Lock()
        self._url = settings.embeddings_url if settings else None
        self._model = settings.model if settings else None
        self._recipe = f"{self._model} {_EMBEDDED_TEXT}"
        self._token = os.environ.get(settings.token_env) if settings and settings.token_env else None
        if settings and settings.token_env and not self._token:
            logger.warning("StarPulse: %s is not set, so embeddings requests carry no credentials", settings.token_env)

    @classmethod
    def open(cls, engine: Engine, settings: Search | None = None) -> SearchIndex | None:
        """The index in `engine`'s database, created when absent; None for a SQLite built without FTS5, which then keeps
        no search. `settings` names the embeddings endpoint, if any."""
        index = cls(engine, settings)
        try:
            with engine.begin() as connection:
                connection.execute(text(_CREATE))
                connection.execute(text(_CREATE_VECTORS))
                connection.execute(text(_CREATE_FACETS))
                if index._url:
                    connection.execute(_DROP_OTHER_RECIPES, {"model": index._recipe})
        except OperationalError as error:
            logger.warning("StarPulse: this SQLite has no FTS5, so the board is not searchable: %s", error)
            return None
        return index

    def index(self, task: BoardTask, finished_at: float | None = None) -> None:
        """Make the index hold `task` as it is now; a task already held unchanged is left alone.

        `finished_at` is when the task finished, which the feed knows for a task in the done lane; without it a settled
        task finished at its `settled_at` (0, older than any bound, when the board does not say) and any other is open."""
        if finished_at is None and task.settled:
            finished_at = task.settled_at or 0.0
        self.index_fields(
            task.id,
            title=task.title,
            description=task.description,
            criteria=task.acceptance_criteria,
            notes=task.notes,
            lane=task.settled or task.lane,
            labels=task.labels,
            finished_at=finished_at,
        )

    def index_fields(
        self,
        task_id: str,
        *,
        title: str,
        description: str,
        criteria: Sequence[str],
        notes: str,
        lane: str,
        labels: Sequence[str],
        finished_at: float | None = None,
        connection: Connection | None = None,
    ) -> None:
        """Make the index hold these fields of `task_id` as they are now, as `index` does for a task. With `connection`
        the rows are written in its transaction, so a projector's rows and its index rows commit together."""
        facets = {"labels": "\n" + "".join(f"{label}\n" for label in labels), "finished_at": finished_at}
        fields = {
            "task": task_id,
            "title": title,
            "description": description,
            "criteria": "\n".join(criteria),
            "notes": notes,
            "lane": lane,
        }
        digest = hashlib.sha256("\x1f".join(fields.values()).encode()).hexdigest()
        row = _row(task_id)
        with self._lock:
            if connection is not None:
                self._write(connection, row, facets, fields, digest)
            else:
                with self._engine.begin() as own:
                    self._write(own, row, facets, fields, digest)

    def _write(self, connection: Connection, row: int, facets: dict, fields: dict, digest: str) -> None:
        held = connection.execute(_HELD_FACETS, {"row": row}).one_or_none()
        if held is not None and held.finished_at is not None and facets["finished_at"] is not None:
            # a finished task keeps its earliest finish: a restart dates a done-lane entry the history lacks now
            facets["finished_at"] = min(held.finished_at, facets["finished_at"])
        if held is None or tuple(held) != tuple(facets.values()):
            connection.execute(_STORE_FACETS, {"row": row, **facets})
        if connection.execute(_DIGEST, {"row": row}).scalar() == digest:
            return
        connection.execute(_DELETE, {"row": row})
        connection.execute(_DROP_VECTORS, {"row": row})
        connection.execute(_INSERT, {"row": row, "digest": digest, **fields})
        self._dirty.add(row)

    def remove(self, task_id: str) -> None:
        """Drop `task_id` from the index; a task the index does not hold is a no-op."""
        with self._lock, self._engine.begin() as connection:
            connection.execute(_DELETE, {"row": _row(task_id)})
            connection.execute(_DROP_VECTORS, {"row": _row(task_id)})
            connection.execute(_DROP_FACETS, {"row": _row(task_id)})
            self._dirty.add(_row(task_id))

    def search(
        self, query: str, limit: int = 10, *, labels: Sequence[str] = (), finished_since: float | None = None
    ) -> list[dict]:
        """The tasks holding every word of `query`, best first, as `{task, title, lane, score, snippet}`; `score` is
        higher for a better match and `snippet` is the text around it. With an embeddings endpoint the order blends
        each hit's lexical score with the similarity of its vector to the query's, and a task that holds none of the
        query's words is a hit too when its vector is near the query's (its snippet is the task's opening).

        A hit carries every one of `labels`, and with `finished_since` (epoch seconds) a task that finished before it
        is no hit; an open task always may be."""
        match = _match(query)
        if not match:
            return []
        limit = max(1, limit)
        vector = self._embed_query(query)
        filtered, narrowing = _filtered(labels, finished_since, row="row")
        with self._engine.connect() as connection:
            if vector is None:
                rows = connection.execute(
                    text(_SEARCH.format(filtered=filtered)), {"query": match, "limit": limit, **narrowing}
                )
                return [dict(row._mapping) for row in rows]
            rows = connection.execute(
                text(_RANKED.format(filtered=filtered)),
                {"query": match, "model": self._recipe, "limit": max(limit, _POOL), **narrowing},
            )
            hits = [dict(row._mapping) for row in rows]
            lexical = {hit["task"] for hit in hits}
            facets, _ = _filtered(labels, finished_since)
            allowed = (
                set(connection.execute(text(f"SELECT rowid FROM {_TABLE} WHERE 1{facets}"), narrowing).scalars())
                if filtered
                else None
            )
        top = max((hit["score"] for hit in hits), default=0.0) or 1.0
        for hit in hits:
            held = array.array("f")
            if blob := hit.pop("vector"):
                held.frombytes(blob)
            hit["score"] = _LEXICAL_WEIGHT * hit["score"] / top + (1 - _LEXICAL_WEIGHT) * _cosine(vector, held)
        near = self._near_vectors(len(vector))
        # einsum, not `@`: a matrix-vector product through BLAS fans out over every core, which on a busy host costs far
        # more than the 20 MB it reads.
        similarities = np.einsum("ij,j->i", near.matrix, _unit(np.array(vector, dtype=np.float32)))
        near_enough = [
            at
            for at in np.flatnonzero(similarities >= _RECALL_FLOOR)
            if near.hits[at]["task"] not in lexical and (allowed is None or near.rows[at] in allowed)
        ]
        for at in sorted(near_enough, key=lambda at: -similarities[at])[
            :limit
        ]:  # no more than `limit` can survive the cut
            hits.append({**near.hits[at], "score": (1 - _LEXICAL_WEIGHT) * float(similarities[at])})
        return sorted(hits, key=lambda hit: -hit["score"])[:limit]

    def _near_vectors(self, dimension: int) -> _Near:
        """Every embedded task whose vector has `dimension` numbers, with the vectors read again only for the rows a
        write has changed since the last read (all of them the first time, or when too many changed to name)."""
        with self._refreshing:
            with self._lock:
                changed, self._dirty = self._dirty, set()
            held = self._near
            stale = time.monotonic() - self._read_at >= _SHARED_REFRESH_S
            if held is not None and (held.matrix.shape[1] != dimension or len(changed) > _RELOAD_AT or stale):
                held = None
            if held is not None and not changed:
                return held
            try:
                self._near = self._read_near(held, changed, dimension)
                self._read_at = time.monotonic()
            except BaseException:
                with self._lock:
                    self._dirty |= changed
                raise
            return self._near

    def _read_near(self, held: _Near | None, changed: set[int], dimension: int) -> _Near:
        """`held` with the vectors of the `changed` rows read again, or every vector when nothing is held."""
        query = _EMBEDDED if held is None else _EMBEDDED_ROWS
        with self._engine.connect() as connection:
            result = connection.execute(query, {"model": self._recipe, "rows": list(changed)})
            fresh = [dict(row._mapping) for row in result if len(row.vector) == dimension * 4]
        blobs = b"".join(row.pop("vector") for row in fresh)
        rows = [row.pop("row") for row in fresh]
        matrix = _unit(np.frombuffer(blobs, dtype=np.float32).reshape(-1, dimension))
        if held is None:
            return _Near(rows, fresh, matrix)
        kept = ~np.isin(held.rows, list(changed))
        return _Near(
            [row for row, keep in zip(held.rows, kept, strict=True) if keep] + rows,
            [hit for hit, keep in zip(held.hits, kept, strict=True) if keep] + fresh,
            np.concatenate([held.matrix[kept], matrix]),
        )

    def embed_pending(self) -> int:
        """Embed every task the index holds no vector of the configured model for, and return how many were stored; 0
        with no endpoint configured. An endpoint that fails raises `EmbeddingError` and leaves the rest pending."""
        stored = 0
        while self._url:
            with self._engine.connect() as connection:
                rows = connection.execute(_PENDING, {"model": self._recipe, "limit": _BATCH}).all()
            if not rows:
                break
            texts = [f"{r.title}\n{r.description}"[:_TEXT_LIMIT] for r in rows]
            vectors = self._embed(texts)
            with self._lock, self._engine.begin() as connection:
                done = [
                    row.row
                    for row, vector in zip(rows, vectors, strict=True)
                    if connection.execute(
                        _STORE,
                        {
                            "row": row.row,
                            "model": self._recipe,
                            "vector": array.array("f", vector).tobytes(),
                            "digest": row.digest,
                        },
                    ).rowcount
                ]
                self._dirty.update(done)
            stored += len(done)
            if not done:
                break
        return stored

    def keep_embedding(self, stop: threading.Event) -> None:
        """Run `embed_pending` every few seconds until `stop` is set; a failed pass is logged and retried later."""
        delay = _POLL
        while not stop.wait(delay):
            try:
                self.embed_pending()
                delay = _POLL
            except (EmbeddingError, SQLAlchemyError) as exc:
                logger.warning("StarPulse: cannot embed tasks for search: %s", exc)
                delay = _RETRY

    def _embed_query(self, query: str) -> array.array | None:
        """`query`'s vector, or None when no endpoint is configured or it cannot be reached: the order stays lexical."""
        if not self._url:
            return None
        try:
            return array.array("f", self._embed([query], _QUERY_TIMEOUT)[0])
        except EmbeddingError as exc:
            logger.warning("StarPulse: cannot embed the search query, ranking lexically: %s", exc)
            return None

    def _embed(self, texts: list[str], timeout: float = _TIMEOUT) -> list[list[float]]:
        """One vector per text from the endpoint (OpenAI-compatible: `POST {model, input}`, `data[].embedding`)."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(
            self._url, json.dumps({"model": self._model, "input": texts}).encode(), headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = sorted(json.load(response)["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"{self._url}: {exc}") from exc
        numbers = all(isinstance(v, list) and v and all(isinstance(x, int | float) for x in v) for v in vectors)
        if len(vectors) != len(texts) or not numbers:
            raise EmbeddingError(f"{self._url} did not answer with one vector of numbers per text")
        return vectors
