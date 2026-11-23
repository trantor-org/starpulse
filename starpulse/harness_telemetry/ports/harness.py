"""The Harness port: what StarPulse needs from the agent client a session runs in, whichever client it is."""

from collections.abc import Mapping
from typing import Protocol


class HarnessPort(Protocol):
    name: str
    skills_dir: str
    """The directory, relative to a project root, the harness loads skills from."""
    events: Mapping[str, str]
    """Each hook event or log record kind the harness emits, mapped onto the shared session event it moves."""

    def launch(self, task: str, verb: str, profile: str | None) -> list[str]:
        """The command that starts `task`'s session, `verb` its prompt and `profile` the agent it runs as."""

    def model(self, tier: str, effort: str | None) -> str:
        """The model `tier` runs at `effort` on this harness."""
