"""The autopilot's on/off switch: a file beside the config, so a restart keeps it and flipping it needs no config edit."""

import json
import os
from pathlib import Path

#: Where the switch lives, in the directory of the `--config` file (the working directory without one).
TOGGLE_FILE = "starpulse-autopilot.json"


class Toggle:
    """Whether the autopilot admits tasks: the flag in `path`, off unless the file says `true`.

    A missing or unreadable file leaves it off, so a fresh install admits nothing until the operator turns it on.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self) -> bool:
        try:
            return json.loads(self.path.read_text())["enabled"] is True
        except OSError, ValueError, KeyError, TypeError:
            return False

    def set(self, value: bool) -> None:
        scratch = self.path.with_name(f"{self.path.name}.tmp")
        scratch.write_text(json.dumps({"enabled": value}))
        os.replace(scratch, self.path)  # a reader sees the old file or the new one, never half of one
