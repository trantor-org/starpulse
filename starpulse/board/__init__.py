"""The Board context: its public API is the adapter seam, and the layers behind it are `model` and `adapters`."""

import importlib
from typing import TYPE_CHECKING

from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.board.model.seam import (
    DEFAULT_TYPE,
    AssigneeWriter,
    Board,
    DocArchiver,
    DocCreator,
    DocEditor,
    DocLister,
    DocReader,
    DocRestorer,
    MilestoneArchiver,
    MilestoneCreator,
    MilestoneEditor,
    MilestoneLister,
    MilestoneReader,
    MoveWriter,
    RetiredImporter,
    RetiredReader,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
    TaskRetirer,
    Written,
    load,
    module_name,
)

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed, BoardStore, Followed, Resumable

#: The feed's names load on first use: it reads the whole ledger, which an adapter that only needs the seam does not.
_FEED = frozenset({"BoardFeed", "BoardStore", "Followed", "Resumable"})

__all__ = [
    "DEFAULT_TYPE",
    "AssigneeWriter",
    "Board",
    "BoardFeed",
    "BoardStore",
    "CommitKeys",
    "DocArchiver",
    "DocCreator",
    "DocEditor",
    "DocLister",
    "DocReader",
    "DocRestorer",
    "Followed",
    "MilestoneArchiver",
    "MilestoneCreator",
    "MilestoneEditor",
    "MilestoneLister",
    "MilestoneReader",
    "MoveWriter",
    "Resumable",
    "RetiredImporter",
    "RetiredReader",
    "TaskArchiver",
    "TaskCompleter",
    "TaskCreator",
    "TaskEditor",
    "TaskReader",
    "TaskRestorer",
    "TaskRetirer",
    "UpstreamBacklog",
    "Written",
    "load",
    "module_name",
]


def __getattr__(name: str) -> object:
    if name not in _FEED:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module("starpulse.board.board_feed"), name)
