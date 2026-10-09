"""The feed a board adapter places tasks on; the implementation is in `starpulse._internal.feed.board_feed`."""

from starpulse._internal.feed.board_feed import BoardFeed, BoardStore, Followed, Resumable
from starpulse._internal.feed.board_feed import stream_id as stream_id  # trantor's follower reads it; not in the declared surface

__all__ = ["BoardFeed", "BoardStore", "Followed", "Resumable"]
