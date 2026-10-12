"""The task key an adapter declares. It imports no model library, so a board load builds it without `pydantic`;
`starpulse.contracts` re-exports it beside the models."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskKeys:
    """How one adapter names its tasks, and which branch belongs to which task."""

    #: Matches a whole task key, e.g. `PROJ-45` or `ENG-123`.
    key: re.Pattern[str]
    #: Matches a branch name, bare or under `refs/heads/`; group 1 is the key, or what `key_format` wraps into it.
    branch: re.Pattern[str]
    #: Wraps group 1 of `branch` into the key: `PROJ-{}` turns the `45` of `feature/proj-45-x` into `PROJ-45`.
    key_format: str = "{}"

    def matches(self, task: str) -> bool:
        """Whether `task` is a whole key of this scheme."""
        return self.key.fullmatch(task) is not None

    def for_branch(self, ref: str | None) -> str | None:
        """The task key a branch names, or None for a branch that names no task."""
        match = self.branch.match(ref) if ref else None
        return self.key_format.format(match[1]) if match else None

    def canonical(self, task: str) -> str:
        """`task` spelled as this scheme names it (`task-45` is `TASK-45` under a `TASK-{}` format); text that is no
        key, or that no branch pattern reads, comes back as it was."""
        return (self.for_branch(task) if self.matches(task) else None) or task
