"""`starpulse worker search`: the Search context's embedding catch-up (the thread that fills a vector for each task the
index holds text of) as its own process, beside `serve`.

It reads the config and the database `serve` does and meets `serve` only in the index tables there: `serve` writes the
index rows (`feed.index_tasks`) and this worker writes the vectors, and a search in `serve` rereads the vectors on a
timer (`starpulse.board.adapters.search`). The catch-up is resumable by construction: `SearchIndex.embed_pending` embeds
what holds no vector of the configured model and stores each batch in one transaction, keyed by the text's digest, so a
new process embeds exactly what the last one left and neither drops nor repeats an embedding. With no `embeddings_url`
there is nothing to embed, and the worker holds idle rather than exit under the supervisor that would restart it.
`SIGTERM` stops it; `SIGHUP` re-reads the config and, as the thread is built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from starpulse.board.adapters.search import SearchIndex
from starpulse.board.bin.blocks import BoardConfig, search_built_blocks
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url

logger = logging.getLogger(__name__)


def reload(path: Path, config: BoardConfig, load: Callable[[Path | None], BoardConfig]) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if search_built_blocks(new) != search_built_blocks(config):
        logger.warning("reload: a database or search setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Search setting changed")


def start(
    config: BoardConfig,
    path: Path | None,
    base: Path,
    log: EventLog | None,
    stop: threading.Event,
    *,
    load: Callable[[Path | None], BoardConfig],
) -> Callable[[], None]:
    """Start the embedding catch-up over `log` until `stop` is set, and return its reload. With no `embeddings_url`
    nothing starts and `log` may be None. Raises `ValueError` when the database keeps no search index."""
    if not config.search.embeddings_url or log is None:
        logger.info("no [search] embeddings_url; the search worker has nothing to embed")
    else:
        index = SearchIndex.open(log.engine, config.search)
        if index is None:
            raise ValueError(f"{path}: the database keeps no search index (SQLite with FTS5 is required)")
        threading.Thread(target=index.keep_embedding, args=(stop,), name="search-embeddings", daemon=True).start()
    return lambda: reload(path, config, load)


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], BoardConfig],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the embedding catch-up; `runtime` passes `hold`, as no context imports it."""
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    stop = threading.Event()
    log = EventLog(database_url(config.database_url, base)) if config.search.embeddings_url else None
    try:
        reload_config = start(config, path, base, log, stop, load=load)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
