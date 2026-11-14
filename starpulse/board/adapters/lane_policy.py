"""The policy that governs the lanes: the database's rows when it holds any, else the board machine and `[board]`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from starpulse.board.adapters import policy_store
from starpulse.board.model.lane_surface import lanes_of
from starpulse.board.model.policy import Policy, from_files
from starpulse.machine_engine.adapters.machine_loader import read_document


def load_policy(engine: Engine, board: dict[str, Any], base: Path) -> tuple[str, Policy]:
    """The policy and where it came from, `database` or `files`."""
    machine = board.get("machine")
    return policy_store.load(engine, lambda: from_files(read_document(base / str(machine)) if machine else {}, board))


def lane_surfaces(engine: Engine, board: dict[str, Any], base: Path) -> dict[str, dict[str, Any]]:
    """What `/api/machines` serves under `lanes`: each lane's surface from the governing policy."""
    return lanes_of(load_policy(engine, board, base)[1])
