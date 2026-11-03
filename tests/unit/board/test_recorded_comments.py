"""A board does not repeat the latest hold or flag a task already records, and does write one that changed."""

from starpulse.board.adapters.native import _recorded
from starpulse.board.model.seam import FLAGGED, HELD


def test_a_flag_is_recorded_only_as_the_latest_flag() -> None:
    first, second = f"{FLAGGED} TASK-2 is Proposed.", f"{FLAGGED} TASK-404 is not on the board."
    comments = [{"text": first}, {"text": f"{HELD} wait"}, {"text": second}]

    assert _recorded(second, comments)
    assert not _recorded(first, comments)  # a flag that returns after another is written again


def test_a_flag_and_a_hold_do_not_record_each_other() -> None:
    assert not _recorded(f"{FLAGGED} TASK-2 is Proposed.", [{"text": f"{HELD} TASK-2 is Proposed."}])
