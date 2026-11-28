"""Full-text search over the board's tasks, kept in the instance's own database.

The index is an SQLite FTS5 table of each placed task's id, title, description, acceptance criteria, notes and comments. It lives
beside the event log on the instance. A row is keyed by a
rowid derived from the task id, so replacing a task and reading its stored digest are point lookups, and a task placed
again unchanged, as every task is on a restart, writes nothing.

With an embeddings endpoint configured (`[search] embeddings_url`) the index also keeps one vector per task and model,
of the task's title and description, in a table beside the FTS5 one, and ranks a query's lexical hits by a blend of
their bm25 score and the cosine similarity between the query's vector and theirs. Embedding never runs on the feed's path: `index` writes the FTS5 row
and `embed_pending` (run by `keep_embedding`) catches the vectors up. Without an endpoint nothing calls out, and an
endpoint that fails leaves the lexical order.
"""

import array
import dataclasses
import functools
import hashlib
import http.client
import json
import logging
import os
import threading
import urllib.request
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

import numpy as np
from opentelemetry import trace
from sqlalchemy import Connection, Engine, bindparam, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from starpulse.board.model.search_config import Search
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

_TABLE = "starpulse_task_search"
_CREATE = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING fts5("
    "task, title, description, criteria, notes, comments, lane UNINDEXED, digest UNINDEXED, tokenize = 'porter unicode61')"
)
#: What a match in each column is worth, in the column order above: a title says most, a note least.
_WEIGHTS = "4, 10, 2, 1, 1, 1, 0, 0"
#: The indexed text columns in table order, which `snippet` counts from 0: a hit names the first holding a query word.
_FIELDS = ("task", "title", "description", "criteria", "notes", "comments")
_MARK = "char(2), char(3)"
#: The column index of the first field with a match, -1 when none shows one; `snippet` takes it as its column.
_HIT_COLUMN = (
    "CASE "
    + " ".join(f"WHEN instr(snippet({_TABLE}, {at}, {_MARK}, '', 1), char(2)) THEN {at}" for at in range(len(_FIELDS)))
    + " ELSE -1 END"
)
_LOCATED = f"{_HIT_COLUMN} AS field, snippet({_TABLE}, {_HIT_COLUMN}, '', '', '…', 16) AS snippet"
_SNIPPET_CHARS = 160
#: The lexical query: MATCH first into a MATERIALIZED CTE, then `{filtered}` (facets) on those rowids. ANDing the
#: facets IN onto MATCH makes SQLite look up each facet rowid in FTS (`0:=M`) and cost grows with rows × words. The
#: CTE holds a match's rowid and rank alone (`{task}` adds the key a `before` filter reads): reading `task`, `title` and
#: `lane` of every match cost five times its wall time when a word most tasks hold matched thousands. Only the `best` rows are
#: read and located (`snippet` runs seven times a row).
_BEST = (
    f"WITH matched AS MATERIALIZED ("
    f"SELECT {_TABLE}.rowid AS row{{task}}, bm25({_TABLE}, {_WEIGHTS}) AS rank FROM {_TABLE} WHERE {_TABLE} MATCH :query"
    f"), best AS MATERIALIZED (SELECT row, rank FROM matched WHERE 1{{filtered}} ORDER BY rank, row LIMIT :limit) "
)
_SEARCH = (
    f"{_BEST}SELECT {_TABLE}.task, {_TABLE}.title, {_TABLE}.lane, -best.rank AS score, {_LOCATED} FROM best JOIN {_TABLE} "
    f"ON {_TABLE}.rowid = best.row WHERE {_TABLE} MATCH :query ORDER BY best.rank, {_TABLE}.task"
)
_DIGEST = text(f"SELECT digest FROM {_TABLE} WHERE rowid = :row")
_DELETE = text(f"DELETE FROM {_TABLE} WHERE rowid = :row")
_VECTORS = "starpulse_task_vectors"
#: `id` only grows (AUTOINCREMENT), so a vector stored again after its row was dropped never takes the old row's id:
#: a search tells a changed vector from its task's row and id alone, without reading the vector.
_CREATE_VECTORS = (
    f"CREATE TABLE IF NOT EXISTS {_VECTORS} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "task_row INTEGER NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL, UNIQUE (task_row, model))"
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
    f"{_BEST}SELECT {_TABLE}.task, {_TABLE}.title, {_TABLE}.lane, -best.rank AS score, best.row AS row "
    f"FROM best JOIN {_TABLE} ON {_TABLE}.rowid = best.row ORDER BY best.rank, {_TABLE}.task"
)
#: Where a query's words sit in the named rows: `snippet` runs seven times a row, so only a ranked query's survivors of the
#: cut to `limit` are located, never its whole pool.
_LOCATE = text(
    f"SELECT {_TABLE}.rowid AS row, {_LOCATED} FROM {_TABLE} "
    f"WHERE {_TABLE} MATCH :query AND {_TABLE}.rowid IN (SELECT value FROM json_each(:rows))"
)
#: Every embedded task, for a query whose meaning (not its words) is what is wanted; `snippet` is the task's opening.
_EMBEDDED_SELECT = (
    f"SELECT {_TABLE}.rowid AS row, task, title, lane, substr(description, 1, {_SNIPPET_CHARS}) AS snippet, 2 AS field, "
    f"{_VECTORS}.vector AS vector FROM {_TABLE} JOIN {_VECTORS} "
    f"ON {_VECTORS}.task_row = {_TABLE}.rowid AND {_VECTORS}.model = :model"
)
_EMBEDDED = text(_EMBEDDED_SELECT)
#: Only the named rows of `_EMBEDDED`, which is how the held vectors catch up with the writes made since.
_EMBEDDED_ROWS = text(f"{_EMBEDDED_SELECT} WHERE {_TABLE}.rowid IN :rows").bindparams(bindparam("rows", expanding=True))
#: The tasks that may lack a vector, a row each: a write that drops a task's vector adds it, a stored vector removes it,
#: and `open` adds the tasks lacking one, so a pass with nothing to embed reads one empty table, never every task. Created
#: with the index, the `CREATE IF NOT EXISTS` of the others.
_PENDING_TABLE = "starpulse_task_pending"
_CREATE_PENDING = f"CREATE TABLE IF NOT EXISTS {_PENDING_TABLE} (task_row INTEGER PRIMARY KEY)"
_MARK_PENDING = text(f"INSERT OR IGNORE INTO {_PENDING_TABLE} (task_row) VALUES (:row)")
_CLEAR_PENDING = text(f"DELETE FROM {_PENDING_TABLE} WHERE task_row = :row")
_MARK_UNEMBEDDED = text(
    f"INSERT OR IGNORE INTO {_PENDING_TABLE} (task_row) SELECT task_row FROM {_FACETS} "
    f"WHERE task_row NOT IN (SELECT task_row FROM {_VECTORS} WHERE model = :model)"
)
_PENDING = text(
    f"SELECT {_TABLE}.rowid AS row, title, description, digest FROM {_PENDING_TABLE} CROSS JOIN {_TABLE} "
    f"ON {_TABLE}.rowid = {_PENDING_TABLE}.task_row LIMIT :limit"
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
#: The vectors table's row count and newest id. Other processes write it (`starpulse worker search` stores vectors, the
#: board worker's fold drops them), and as ids only grow, no write leaves both unchanged: an unchanged pair keeps the
#: held vectors without reading a key.
_SHAPE = text(f"SELECT count(*), coalesce(max(rowid), 0) FROM {_VECTORS}")
#: The number of floats in one stored vector of the model, which `warm` reads before it knows what a search would ask for.
_DIMENSION = text(f"SELECT length(vector) / 4 FROM {_VECTORS} WHERE model = :model LIMIT 1")
#: Each vector's task row and id, read from the key index alone (about 20 ms for 17,000 vectors, where reading them all
#: took seconds): a row whose id differs from the held one, or that appeared or went, is the only one read again. One
#: JSON row, never a row per vector: sqlite3 releases and retakes the GIL for each row it hands back, so beside a crowd
#: of busy request threads 19,000 rows took 6 to 11 s.
_KEYS = text(f"SELECT json_group_array(json_array(task_row, rowid)) FROM {_VECTORS} WHERE model = :model")
_TEXT_LIMIT = 8000
_TIMEOUT = 10.0
#: Seconds each attempt at a search query's vector waits, and the attempts made, by a search that waits (`wait=True`) or
#: by the background fill of one that does not. A healthy embedder answers in 1 to 3 s and a cold one is quick on retry.
_QUERY_TIMEOUT = 3.5
_QUERY_ATTEMPTS = 2
#: Query vectors kept (least recently used out first), and background fills in flight at once: a search never embeds
#: its own query, so a repeat finds the vector held and a burst of new queries cannot pile on the endpoint.
_QUERY_VECTORS = 256
_SCAN_THREADS = 4
_SCAN_POOL = ThreadPoolExecutor(_SCAN_THREADS, thread_name_prefix="search-scan")
_FILLING_MAX = 4
#: Seconds the reranker is given to score the candidates of one duplicate search.
_RERANK_TIMEOUT = 30.0
#: Seconds `keep_embedding` waits after a failed pass before the next.
_RETRY = 60.0
_INSERT = text(
    f"INSERT INTO {_TABLE} (rowid, task, title, description, criteria, notes, comments, lane, digest) "
    "VALUES (:row, :task, :title, :description, :criteria, :notes, :comments, :lane, :digest)"
)


def _filtered(
    labels: Sequence[str],
    finished_since: float | None,
    before: tuple[str, int] | None = None,
    *,
    row: str = f"{_TABLE}.rowid",
) -> tuple[str, dict]:
    """The condition, ANDed onto a query's WHERE, that keeps the tasks carrying every one of `labels`, not finished
    before `finished_since` (epoch seconds) and, with `before` (a key's prefix and number), of that prefix and a lower
    number, with its parameters; no condition when none narrows.

    `row` is the outer column compared to `task_row` (the MATCH CTE's `row`, or `{_TABLE}.rowid` for a facets-only
    select); both selects carry the `task` column `before` reads."""
    conditions = [f"instr(labels, :label_{at}) > 0" for at in range(len(labels))]
    parameters: dict = {f"label_{at}": f"\n{label}\n" for at, label in enumerate(labels)}
    if finished_since is not None:
        conditions.append("(finished_at IS NULL OR finished_at >= :finished_since)")
        parameters["finished_since"] = finished_since
    clause = (
        f" AND EXISTS (SELECT 1 FROM {_FACETS} WHERE task_row = {row} AND {' AND '.join(conditions)})"
        if conditions
        else ""
    )
    if before is not None:
        clause += (
            " AND substr(task, 1, length(:before_prefix)) = :before_prefix"
            " AND substr(task, length(:before_prefix) + 1) GLOB '[0-9]*'"
            " AND substr(task, length(:before_prefix) + 1) NOT GLOB '*[^0-9]*'"
            " AND CAST(substr(task, length(:before_prefix) + 1) AS INTEGER) < :before_number"
        )
        parameters |= {"before_prefix": f"{before[0]}-", "before_number": before[1]}
    return clause, parameters


def _row(task_id: str) -> int:
    """The index's rowid for a task: 56 bits of its id's hash, so a collision between two tasks of a board is a
    one-in-ten-billion event."""
    return int.from_bytes(hashlib.blake2b(task_id.encode(), digest_size=7).digest(), "big")


def _scan(matrix: np.ndarray, query: np.ndarray) -> list[Future[np.ndarray]]:
    # einsum, not `@`: a matrix-vector product through BLAS fans out over every core, which on a busy host costs far more
    # than the 20 MB it reads. The scan is memory-bound and releases the GIL, so a few threads read it side by side while
    # the caller runs its ranked query.
    step = max(1, -(-len(matrix) // _SCAN_THREADS))
    return [
        _SCAN_POOL.submit(np.einsum, "ij,j->i", matrix[at : at + step], query)
        for at in range(0, max(len(matrix), 1), step)
    ]


def _unit(vectors: np.ndarray) -> np.ndarray:
    """`vectors` (one, or one per row) scaled to length 1; a zero vector stays zero, which makes every similarity to it
    0."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


def _drop_without_comments(connection: Connection) -> None:
    """Drops an index made before it held comments, whose columns cannot change; `index` fills the new one again."""
    columns = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({_TABLE})")}
    if columns and "comments" not in columns:
        connection.exec_driver_sql(f"DROP TABLE {_TABLE}")


def _ids_grow(connection: Connection) -> None:
    """Copies a vectors table made before its ids only grew into one whose ids do, keeping every vector."""
    made = connection.exec_driver_sql(f"SELECT sql FROM sqlite_master WHERE name = '{_VECTORS}'").scalar()
    if made is None or "AUTOINCREMENT" in made:
        return
    connection.exec_driver_sql(f"ALTER TABLE {_VECTORS} RENAME TO {_VECTORS}_old")
    connection.exec_driver_sql(_CREATE_VECTORS)
    connection.exec_driver_sql(
        f"INSERT INTO {_VECTORS} (task_row, model, vector) SELECT task_row, model, vector FROM {_VECTORS}_old"
    )
    connection.exec_driver_sql(f"DROP TABLE {_VECTORS}_old")


def _named(hit: dict) -> dict:
    """`hit` with its `field` column index as the field's name; a match in no one column (-1) is the title's."""
    hit["field"] = _FIELDS[hit["field"] if hit["field"] >= 0 else 1]
    return hit


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

    @functools.cached_property
    def position(self) -> dict[int, int]:
        """Each task rowid's row in `matrix`."""
        return {row: at for at, row in enumerate(self.rows)}


class EmbeddingError(RuntimeError):
    """The embeddings endpoint did not answer with a vector for every text it was sent."""


class SearchIndex:
    """An FTS5 index of each placed task's id, title, description, acceptance criteria, notes and comments."""

    def __init__(self, engine: Engine, settings: Search | None = None) -> None:
        self._engine = engine
        self._lock = threading.Lock()
        #: The embedded tasks' unit vectors, read once, with the `_SHAPE` and `_KEYS` they were read at: the next search
        #: reads again only the rows whose key changed, whichever process wrote them.
        self._near: _Near | None = None
        self._shape: tuple[int, int] | None = None
        self._keys: dict[int, int] = {}
        #: Held by the one search refreshing `_near`, which reads and normalises outside `_lock` so a write never waits
        #: for it.
        self._refreshing = threading.Lock()
        self._queries: OrderedDict[str, array.array] = OrderedDict()
        self._filling: set[str] = set()
        #: Guards `_queries` and `_filling` alone, so a search never waits behind a write holding `_lock`.
        self._queries_lock = threading.Lock()
        self._url = settings.embeddings_url if settings else None
        self._model = settings.model if settings else None
        self._recipe = f"{self._model} {_EMBEDDED_TEXT}"
        self._rerank = settings if settings and settings.rerank_url else None
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
                _drop_without_comments(connection)
                connection.execute(text(_CREATE))
                _ids_grow(connection)
                connection.execute(text(_CREATE_VECTORS))
                connection.execute(text(_CREATE_FACETS))
                connection.execute(text(_CREATE_PENDING))
                if index._url:
                    connection.execute(_DROP_OTHER_RECIPES, {"model": index._recipe})
                    connection.execute(_MARK_UNEMBEDDED, {"model": index._recipe})
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
            comments=task.comments,
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
        comments: str = "",
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
            "comments": comments,
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
        connection.execute(_MARK_PENDING, {"row": row})
        connection.execute(_INSERT, {"row": row, "digest": digest, **fields})

    def remove(self, task_id: str) -> None:
        """Drop `task_id` from the index; a task the index does not hold is a no-op."""
        with self._lock, self._engine.begin() as connection:
            connection.execute(_DELETE, {"row": _row(task_id)})
            connection.execute(_DROP_VECTORS, {"row": _row(task_id)})
            connection.execute(_CLEAR_PENDING, {"row": _row(task_id)})
            connection.execute(_DROP_FACETS, {"row": _row(task_id)})

    def search(
        self,
        query: str,
        limit: int = 10,
        *,
        labels: Sequence[str] = (),
        finished_since: float | None = None,
        before: tuple[str, int] | None = None,
        wait: bool = False,
    ) -> list[dict]:
        """The tasks holding every word of `query`, best first, as `{task, title, lane, score, snippet}`; `score` is
        higher for a better match and `snippet` is the text around it. With an embeddings endpoint the order blends
        each hit's lexical score with the similarity of its vector to the query's, and a task that holds none of the
        query's words is a hit too when its vector is near the query's (its snippet is the task's opening).

        The query's vector is the one held from an earlier search of it; a query not yet held answers lexically at
        once and is embedded in the background for the next. With `wait` the search embeds the query itself first
        (up to `_QUERY_ATTEMPTS` times `_QUERY_TIMEOUT` seconds) and blends it.

        A hit carries every one of `labels`, and with `finished_since` (epoch seconds) a task that finished before it
        is no hit; an open task always may be. With `before` (a task key's prefix and number) a hit is a task of its prefix with a lower
        number, created before it; every filter applies before `limit` cuts.

        Under a request's trace the vector's lookup or embedding is an `embed` span."""
        match = _match(query)
        if not match:
            return []
        limit = max(1, limit)
        with trace.get_tracer("starpulse").start_as_current_span("embed"):
            vector = self._query_vector(query, wait)
        filtered, narrowing = _filtered(labels, finished_since, before, row="row")
        task = ", task" if before else ""
        if vector is not None:
            near = self._near_vectors(len(vector))
            scan = _scan(near.matrix, _unit(np.array(vector, dtype=np.float32)))
        with self._engine.connect() as connection:
            if vector is None:
                rows = connection.execute(
                    text(_SEARCH.format(filtered=filtered, task=task)), {"query": match, "limit": limit, **narrowing}
                )
                return [_named(dict(row._mapping)) for row in rows]
            rows = connection.execute(
                text(_RANKED.format(filtered=filtered, task=task)),
                {"query": match, "limit": max(limit, _POOL), **narrowing},
            )
            hits = [dict(row._mapping) for row in rows]
            similarities = np.concatenate([part.result() for part in scan])
            # a hit's similarity is read from the held unit vectors, never from its stored blob: reading fifty
            # four-kilobyte blobs and summing each in Python cost more than the product over every task
            lexical = {hit["task"] for hit in hits}
            near_enough = [
                at
                for at in np.flatnonzero(similarities >= _RECALL_FLOOR).tolist()
                if near.hits[at]["task"] not in lexical
            ]
            if filtered and near_enough:
                facets, _ = _filtered(labels, finished_since, before)
                kept = connection.execute(  # one JSON row, as `_KEYS` is: thousands of tasks can be near
                    text(
                        f"SELECT json_group_array(rowid) FROM {_TABLE} "
                        f"WHERE rowid IN (SELECT value FROM json_each(:rows)){facets}"
                    ),
                    {"rows": json.dumps([near.rows[at] for at in near_enough]), **narrowing},
                ).scalar_one()
                allowed = set(json.loads(kept))
                near_enough = [at for at in near_enough if near.rows[at] in allowed]
            top = max((hit["score"] for hit in hits), default=0.0) or 1.0
            for hit in hits:
                held = near.position.get(hit["row"])
                hit["score"] = _LEXICAL_WEIGHT * hit["score"] / top + (1 - _LEXICAL_WEIGHT) * (
                    0.0 if held is None else float(similarities[held])
                )
            for at in sorted(near_enough, key=lambda at: -similarities[at])[
                :limit
            ]:  # no more than `limit` can survive the cut
                hits.append({**near.hits[at], "score": (1 - _LEXICAL_WEIGHT) * float(similarities[at])})
            best = sorted(hits, key=lambda hit: -hit["score"])[:limit]
            located = {
                row.row: _named({"field": row.field, "snippet": row.snippet})
                for row in connection.execute(
                    _LOCATE, {"query": match, "rows": json.dumps([hit["row"] for hit in best if "row" in hit])}
                )
            }
        return [{k: v for k, v in hit.items() if k != "row"} | located.get(hit.get("row"), {}) for hit in best]

    def warm(self) -> None:
        """Read the stored vectors now, so the first search of a new process does not pay for it; a no-op with none."""
        with self._engine.connect() as connection:
            dimension = connection.execute(_DIMENSION, {"model": self._recipe}).scalar()
        if dimension:
            self._near_vectors(dimension)

    def _near_vectors(self, dimension: int) -> _Near:
        """Every embedded task whose vector has `dimension` numbers, with the vectors read again only for the rows any
        process has stored or dropped since the last read (all of them the first time, or when too many changed to
        name). The keys are read before the vectors, so a write between the two is read again next time, never missed."""
        with self._refreshing:
            held = self._near
            if held is not None and held.matrix.shape[1] != dimension:
                held = None
            with self._engine.connect() as connection:
                shape = tuple(connection.execute(_SHAPE).one())
                if held is not None and shape == self._shape:
                    return held
                keys = dict(json.loads(connection.execute(_KEYS, {"model": self._recipe}).scalar_one()))
            changed = {row for row, key in keys.items() if self._keys.get(row) != key} | (self._keys.keys() - keys)
            if len(changed) > _RELOAD_AT:
                held = None
            self._near = self._read_near(held, changed, dimension)
            self._shape, self._keys = shape, keys
            return self._near

    def _read_near(self, held: _Near | None, changed: set[int], dimension: int) -> _Near:
        """`held` with the vectors of the `changed` rows read again, or every vector when nothing is held."""
        query = _EMBEDDED if held is None else _EMBEDDED_ROWS
        with self._engine.connect() as connection:
            result = connection.execute(query, {"model": self._recipe, "rows": list(changed)})
            fresh = [_named(dict(row._mapping)) for row in result if len(row.vector) == dimension * 4]
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
                rows = connection.execute(_PENDING, {"limit": _BATCH}).all()
            if not rows:
                break
            texts = [f"{r.title}\n{r.description}"[:_TEXT_LIMIT] for r in rows]
            vectors = self._embed(texts)
            with self._engine.begin() as connection:
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
                if done:  # an empty list would run the statement once with no row bound
                    connection.execute(_CLEAR_PENDING, [{"row": row} for row in done])
            stored += len(done)
            if not done:
                break
        return stored

    def embed_missing(self) -> tuple[int, int]:
        """`(embedded, indexed)`: how many tasks `embed_pending` gave a vector, and how many tasks the index holds."""
        embedded = self.embed_pending()
        with self._engine.connect() as connection:
            return embedded, connection.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar_one()

    def keep_embedding(self, stop: StopEvent, log: "EventLog") -> None:
        """Run `embed_pending` now and after each commit to the event log (a task change writes its index row) until
        `stop` is set; a failed pass is logged and retried after `_RETRY` seconds."""

        def catch_up() -> None:
            while not stop.is_set():
                try:
                    self.embed_pending()
                    return
                except (EmbeddingError, SQLAlchemyError) as exc:
                    logger.warning("StarPulse: cannot embed tasks for search: %s", exc)
                    # adr-exempt: retry
                    stop.wait(_RETRY)

        log.run_on_wake(stop, catch_up, "StarPulse: the search embedding pass failed")

    def _query_vector(self, query: str, wait: bool) -> array.array | None:
        """`query`'s held vector, else (with `wait`) its embedding, else None with the embedding started in the
        background: None keeps the order lexical, and no endpoint configured calls nothing."""
        if not self._url:
            return None
        with self._queries_lock:
            if (held := self._queries.get(query)) is not None:
                self._queries.move_to_end(query)
                return held
            if not wait:
                if query in self._filling or len(self._filling) >= _FILLING_MAX:
                    return None
                self._filling.add(query)
        if wait:
            return self._embed_query(query)
        try:
            threading.Thread(target=self._fill, args=(query,), daemon=True).start()
        except RuntimeError:
            with self._queries_lock:
                self._filling.discard(query)
            logger.warning("StarPulse: cannot start a thread to embed a search query")
        return None

    def _fill(self, query: str) -> None:
        try:
            self._embed_query(query)
        finally:
            with self._queries_lock:
                self._filling.discard(query)

    def _embed_query(self, query: str) -> array.array | None:
        """`query`'s vector from the endpoint, kept for the next search of it; None when it cannot be reached."""
        for attempt in range(_QUERY_ATTEMPTS):
            try:
                vector = array.array("f", self._embed([query], _QUERY_TIMEOUT)[0])
            except EmbeddingError as exc:
                logger.warning("StarPulse: cannot embed the search query (attempt %d): %s", attempt + 1, exc)
                continue
            with self._queries_lock:
                self._queries[query] = vector
                while len(self._queries) > _QUERY_VECTORS:
                    self._queries.popitem(last=False)
            return vector
        return None

    def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """How well each of `documents` answers `query`, by the configured reranker (`POST {model, query, documents}`,
        `results[].relevance_score` by `index`); None when none is configured."""
        if self._rerank is None:
            return None
        settings = self._rerank
        body = {
            "model": settings.rerank_model,
            "query": settings.rerank_query.replace("{query}", query),
            "documents": [settings.rerank_document.replace("{document}", document) for document in documents],
        }
        try:
            with urllib.request.urlopen(self._request(settings.rerank_url, body), timeout=_RERANK_TIMEOUT) as response:
                scored = {item["index"]: float(item["relevance_score"]) for item in json.load(response)["results"]}
            return [scored[index] for index in range(len(documents))]
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"{settings.rerank_url}: {exc}") from exc

    @staticmethod
    def _request(url: str, body: dict[str, object], token: str | None = None) -> urllib.request.Request:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")

    def _embed(self, texts: list[str], timeout: float = _TIMEOUT) -> list[list[float]]:
        """One vector per text from the endpoint (OpenAI-compatible: `POST {model, input}`, `data[].embedding`)."""
        request = self._request(self._url, {"model": self._model, "input": texts}, self._token)
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
