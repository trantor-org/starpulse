"""The sweeper's `board-files` kind: the search vectors against the tasks. Embedding is catch-up after an endpoint timeout or a
worker restart, so the pass samples the indexed tasks and never counts a correction."""

import logging
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from starpulse.board.adapters.search import EmbeddingError

logger = logging.getLogger(__name__)


def embedding(vectors: Callable[[], tuple[int, int]] | None) -> Callable[[], tuple[int, int]]:
    """The `board-files` pass: `vectors` embeds the tasks that hold none and answers `(embedded, indexed)`; the pass
    answers `(sampled, corrected)` as `indexed` and 0."""

    def run() -> tuple[int, int]:
        try:
            return (vectors()[1] if vectors is not None else 0), 0
        except (EmbeddingError, SQLAlchemyError) as exc:
            logger.warning("StarPulse: the board-files pass cannot embed tasks for search: %s", exc)
            return 0, 0

    return run
