"""Where a session is reached: one owner-only file per session, written when it subscribes.

The inbox socket and token are the harness's grant to the process that runs `starpulse subscribe`, so they are kept
here, in a `0600` file beside the config, and never in the session's JetStream consumer: the server would carry the
token, and a later change of the subscription would overwrite it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from starpulse.sessions.notify import Registration

DIRECTORY = "starpulse-sessions"


def directory(base: Path, configured: str | None) -> Path:
    """The registry the server reads and a session's CLI writes: `[bridge] sessions_dir`, else beside the config."""
    return Path(configured) if configured else base / DIRECTORY


class Registry:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def put(self, key: str, registration: Registration) -> None:
        """Replace the registration of `key` (a session's consumer name) atomically, readable by its owner only."""
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self._directory / f"{key}.json"
        scratch = target.with_suffix(".tmp")
        descriptor = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(asdict(registration), handle)
        scratch.replace(target)

    def get(self, key: str) -> Registration | None:
        try:
            return Registration(**json.loads((self._directory / f"{key}.json").read_text()))
        except (OSError, ValueError, TypeError):
            return None
