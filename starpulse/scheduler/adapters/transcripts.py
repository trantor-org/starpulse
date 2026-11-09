"""When Claude Code last wrote a session's transcript, the liveness the harness machine lacks for a session that claimed a
task after it opened on another branch."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def transcript_written(root: Path) -> Callable[[str], float | None]:
    """A reader of when `<root>/<project>/<session>.jsonl` was last written; None for no session or no transcript."""

    def written(session: str) -> float | None:
        path = next(root.glob(f"*/{session}.jsonl"), None) if session else None
        return path.stat().st_mtime if path is not None else None

    return written
