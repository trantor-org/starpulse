"""The Board context: its public API is the adapter seam, and the layers behind it are `model` and `adapters`."""

import importlib
from typing import TYPE_CHECKING

from starpulse.board.model.commit_keys import CommitKeys
from starpulse.board.model.adapter_types import DEFAULT_TYPE
from starpulse.board.model.seam import (
    AssigneeWriter,
    Board,
    DocArchiver,
    DocCreator,
    DocEditor,
    DocMover,
    DocReader,
    DocRestorer,
    MilestoneArchiver,
    MilestoneCreator,
    MilestoneEditor,
    MilestoneLister,
    MilestoneReader,
    MoveWriter,
    RetiredReader,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
    TaskRetirer,
    Written,
)

if TYPE_CHECKING:
    from starpulse.board.adapters.native_scan import NativeScan
    from starpulse.board.model.board_feed import BoardFeed, BoardStore, Followed, Resumable

#: The feed's names load on first use: it reads the whole ledger, which an adapter that only needs the seam does not.
_FEED = frozenset({"BoardFeed", "BoardStore", "Followed", "Resumable"})
#: The native scan pulls yaml and the file adapters (~0.1 s), which a CLI read verb never needs.
_SCAN = frozenset({"NativeScan"})

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
    "DocReader",
    "DocMover",
    "DocRestorer",
    "Followed",
    "MilestoneArchiver",
    "MilestoneCreator",
    "MilestoneEditor",
    "MilestoneLister",
    "MilestoneReader",
    "MoveWriter",
    "Resumable",
    "RetiredReader",
    "TaskArchiver",
    "TaskCompleter",
    "TaskCreator",
    "TaskEditor",
    "TaskReader",
    "TaskRestorer",
    "TaskRetirer",
    "NativeScan",
    "Written",
]


def __getattr__(name: str) -> object:
    if name in _SCAN:
        return getattr(importlib.import_module("starpulse.board.adapters.native_scan"), name)
    if name not in _FEED:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module("starpulse.board.model.board_feed"), name)
