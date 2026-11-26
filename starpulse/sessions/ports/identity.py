"""How StarPulse tells one harness session from another: the harness adapter's answer, never a read of a process or a transcript by the core."""

from typing import Protocol


class SessionIdentity(Protocol):
    def aliases(self, session: str) -> frozenset[str]:
        """Every id that names `session` in the harness: the id it declares, the other ids it is known by, lowercased names included."""
        ...

    def live(self, session: str) -> bool:
        """Whether the harness confirms the session `session` names, under any of its ids, is running."""
        ...
