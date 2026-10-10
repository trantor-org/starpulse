"""Full-text search over the board's tasks, kept in the instance's own database.

The index is an SQLite FTS5 table of each placed task's id, title, description, acceptance criteria and notes. It lives
beside the event log on the instance and never on a hub (individual data stays on the instance). A row is keyed by a
rowid derived from the task id, so replacing a task and reading its stored digest are point lookups, and a task placed
again unchanged, as every task is on a restart, writes nothing.

With an embeddings endpoint configured (`[search] embeddings_url`) the index also keeps one vector per task and model,
in a table beside the FTS5 one, and ranks a query's lexical hits by a blend of their bm25 score and the cosine
similarity between the query's vector and theirs. Embedding never runs on the feed's path: `index` writes the FTS5 row
and `embed_pending` (run by `keep_embedding`) catches the vectors up. Without an endpoint nothing calls out, and an
endpoint that fails leaves the lexical order.
"""

from __future__ import annotations

import array
import hashlib
import http.client
import json
import logging
import math
import os
import threading
import urllib.request

from sqlalchemy import Engine, text
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
_SEARCH = text(
    f"SELECT task, title, lane, -bm25({_TABLE}, {_WEIGHTS}) AS score, snippet({_TABLE}, -1, '', '', '…', 16) AS snippet "
    f"FROM {_TABLE} WHERE {_TABLE} MATCH :query ORDER BY bm25({_TABLE}, {_WEIGHTS}), task LIMIT :limit"
)
_DIGEST = text(f"SELECT digest FROM {_TABLE} WHERE rowid = :row")
_DELETE = text(f"DELETE FROM {_TABLE} WHERE rowid = :row")
_VECTORS = "starpulse_task_vectors"
_CREATE_VECTORS = (
    f"CREATE TABLE IF NOT EXISTS {_VECTORS} ("
    "task_row INTEGER NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL, PRIMARY KEY (task_row, model))"
)
_DROP_VECTORS = text(f"DELETE FROM {_VECTORS} WHERE task_row = :row")
_RANKED = text(
    f"SELECT task, title, lane, -bm25({_TABLE}, {_WEIGHTS}) AS score, snippet({_TABLE}, -1, '', '', '…', 16) AS snippet, "
    f"{_VECTORS}.vector AS vector FROM {_TABLE} LEFT JOIN {_VECTORS} "
    f"ON {_VECTORS}.task_row = {_TABLE}.rowid AND {_VECTORS}.model = :model "
    f"WHERE {_TABLE} MATCH :query ORDER BY bm25({_TABLE}, {_WEIGHTS}), task LIMIT :limit"
)
_PENDING = text(
    f"SELECT rowid AS row, title, description, criteria, notes, digest FROM {_TABLE} "
    f"WHERE rowid NOT IN (SELECT task_row FROM {_VECTORS} WHERE model = :model) LIMIT :limit"
)
#: Stores a vector only for the text it was made from: a task replaced since is left for the next pass.
_STORE = text(
    f"INSERT OR REPLACE INTO {_VECTORS} (task_row, model, vector) SELECT :row, :model, :vector "
    f"WHERE (SELECT digest FROM {_TABLE} WHERE rowid = :row) = :digest"
)
#: How much of the lexical rank (the rest is the vector's cosine similarity) a hit keeps when a query is embedded.
_LEXICAL_WEIGHT = 0.5
#: How many lexical hits a ranked query blends before it cuts to `limit`, so a near meaning can rise past the top.
_POOL = 50
#: Tasks sent to the endpoint in one request, and the characters of one task's text it is sent.
_BATCH = 32
_TEXT_LIMIT = 8000
_TIMEOUT = 10.0
#: Seconds `keep_embedding` waits between passes, and after a failed one.
_POLL = 5.0
_RETRY = 60.0
_INSERT = text(
    f"INSERT INTO {_TABLE} (rowid, task, title, description, criteria, notes, lane, digest) "
    "VALUES (:row, :task, :title, :description, :criteria, :notes, :lane, :digest)"
)


def _row(task_id: str) -> int:
    """The index's rowid for a task: 56 bits of its id's hash, so a collision between two tasks of a board is a
    one-in-ten-billion event."""
    return int.from_bytes(hashlib.blake2b(task_id.encode(), digest_size=7).digest(), "big")


def _cosine(left: array.array, right: array.array) -> float:
    """The cosine similarity of two vectors; 0 for vectors of different lengths or a zero vector."""
    norm = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(y * y for y in right))
    if len(left) != len(right) or not norm:
        return 0.0
    return sum(x * y for x, y in zip(left, right, strict=True)) / norm


def _match(query: str) -> str:
    """`query` as an FTS5 expression of quoted words, all of which a task must hold, so its punctuation is text and
    never FTS5 syntax (`PROJ-45`, `NEAR`, `title:`)."""
    return " ".join('"' + word.replace('"', '""') + '"' for word in query.split())


class EmbeddingError(RuntimeError):
    """The embeddings endpoint did not answer with a vector for every text it was sent."""


class SearchIndex:
    """An FTS5 index of each placed task's id, title, description, acceptance criteria and notes."""

    def __init__(self, engine: Engine, settings: Search | None = None) -> None:
        self._engine = engine
        self._lock = threading.Lock()
        self._url = settings.embeddings_url if settings else None
        self._model = settings.model if settings else None
        self._token = os.environ.get(settings.token_env) if settings and settings.token_env else None
        if settings and settings.token_env and not self._token:
            logger.warning("StarPulse: %s is not set, so embeddings requests carry no credentials", settings.token_env)

    @classmethod
    def open(cls, engine: Engine, settings: Search | None = None) -> SearchIndex | None:
        """The index in `engine`'s database, created when absent; None for a database that is not SQLite or whose
        SQLite was built without FTS5, which then keeps no search. `settings` names the embeddings endpoint, if any."""
        if engine.dialect.name != "sqlite":
            return None
        try:
            with engine.begin() as connection:
                connection.execute(text(_CREATE))
                connection.execute(text(_CREATE_VECTORS))
        except OperationalError as error:
            logger.warning("StarPulse: this SQLite has no FTS5, so the board is not searchable: %s", error)
            return None
        return cls(engine, settings)

    def index(self, task: BoardTask) -> None:
        """Make the index hold `task` as it is now; a task already held unchanged is left alone."""
        lane = task.settled or task.lane
        fields = {
            "task": task.id,
            "title": task.title,
            "description": task.description,
            "criteria": "\n".join(task.acceptance_criteria),
            "notes": task.notes,
            "lane": lane,
        }
        digest = hashlib.sha256("\x1f".join(fields.values()).encode()).hexdigest()
        row = _row(task.id)
        with self._lock, self._engine.begin() as connection:
            if connection.execute(_DIGEST, {"row": row}).scalar() == digest:
                return
            connection.execute(_DELETE, {"row": row})
            connection.execute(_DROP_VECTORS, {"row": row})
            connection.execute(_INSERT, {"row": row, "digest": digest, **fields})

    def remove(self, task_id: str) -> None:
        """Drop `task_id` from the index; a task the index does not hold is a no-op."""
        with self._lock, self._engine.begin() as connection:
            connection.execute(_DELETE, {"row": _row(task_id)})
            connection.execute(_DROP_VECTORS, {"row": _row(task_id)})

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """The tasks holding every word of `query`, best first, as `{task, title, lane, score, snippet}`; `score` is
        higher for a better match and `snippet` is the text around it. With an embeddings endpoint the order blends
        each hit's lexical score with the similarity of its vector to the query's."""
        match = _match(query)
        if not match:
            return []
        limit = max(1, limit)
        vector = self._embed_query(query)
        with self._engine.connect() as connection:
            if vector is None:
                rows = connection.execute(_SEARCH, {"query": match, "limit": limit})
                return [dict(row._mapping) for row in rows]
            rows = connection.execute(_RANKED, {"query": match, "model": self._model, "limit": max(limit, _POOL)})
            hits = [dict(row._mapping) for row in rows]
        top = max((hit["score"] for hit in hits), default=0.0) or 1.0
        for hit in hits:
            held = array.array("f")
            if blob := hit.pop("vector"):
                held.frombytes(blob)
            hit["score"] = _LEXICAL_WEIGHT * hit["score"] / top + (1 - _LEXICAL_WEIGHT) * _cosine(vector, held)
        return sorted(hits, key=lambda hit: -hit["score"])[:limit]

    def embed_pending(self) -> int:
        """Embed every task the index holds no vector of the configured model for, and return how many were stored; 0
        with no endpoint configured. An endpoint that fails raises `EmbeddingError` and leaves the rest pending."""
        stored = 0
        while self._url:
            with self._engine.connect() as connection:
                rows = connection.execute(_PENDING, {"model": self._model, "limit": _BATCH}).all()
            if not rows:
                break
            texts = ["\n".join((r.title, r.description, r.criteria, r.notes))[:_TEXT_LIMIT] for r in rows]
            vectors = self._embed(texts)
            with self._lock, self._engine.begin() as connection:
                done = sum(
                    connection.execute(
                        _STORE,
                        {
                            "row": row.row,
                            "model": self._model,
                            "vector": array.array("f", vector).tobytes(),
                            "digest": row.digest,
                        },
                    ).rowcount
                    for row, vector in zip(rows, vectors, strict=True)
                )
            stored += done
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
            return array.array("f", self._embed([query])[0])
        except EmbeddingError as exc:
            logger.warning("StarPulse: cannot embed the search query, ranking lexically: %s", exc)
            return None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text from the endpoint (OpenAI-compatible: `POST {model, input}`, `data[].embedding`)."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(
            self._url, json.dumps({"model": self._model, "input": texts}).encode(), headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                data = sorted(json.load(response)["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"{self._url}: {exc}") from exc
        numbers = all(isinstance(v, list) and v and all(isinstance(x, int | float) for x in v) for v in vectors)
        if len(vectors) != len(texts) or not numbers:
            raise EmbeddingError(f"{self._url} did not answer with one vector of numbers per text")
        return vectors
