"""`starpulse worker search`: the Search context's embedding catch-up (the thread that fills a vector for each task the
index holds text of) as its own process, beside `serve`.

It reads the config and the database `serve` does and meets `serve` only in the index tables there: `serve` writes the
index rows (`feed.index_tasks`) and this worker writes the vectors, and a search in `serve` rereads the vectors on a
timer (`starpulse._internal.feed.search`). The catch-up is resumable by construction: `SearchIndex.embed_pending` embeds
what holds no vector of the configured model and stores each batch in one transaction, keyed by the text's digest, so a
new process embeds exactly what the last one left and neither drops nor repeats an embedding. With no `embeddings_url`
there is nothing to embed, and the worker holds idle rather than exit under the supervisor that would restart it.
`SIGTERM` stops it; `SIGHUP` re-reads the config and, as the thread is built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from starpulse._internal.server.blocks import search_built_blocks
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.feed.search import SearchIndex
from starpulse._internal.server.hold import hold
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url

logger = logging.getLogger(__name__)


def reload(path: Path, config: Config) -> None:
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


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    stop = threading.Event()
    if not config.search.embeddings_url:
        logger.info("no [search] embeddings_url; the search worker has nothing to embed")
    else:
        index = SearchIndex.open(EventLog(database_url(config.database_url, base)).engine, config.search)
        if index is None:
            parser.exit(1, f"{path}: the database keeps no search index (SQLite with FTS5 is required)\n")
        threading.Thread(target=index.keep_embedding, args=(stop,), name="search-embeddings", daemon=True).start()
    hold(stop, lambda: reload(path, config))
