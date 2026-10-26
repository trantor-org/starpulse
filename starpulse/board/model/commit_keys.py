"""A runs instance's `[runs.commit]` keys, which pair a run with the Board transition it applied."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommitKeys:
    """The run parameters of one runs instance that carry a commit or a task: a key left out is a parameter the
    instance's workflows do not take."""

    after: str | None = None
    """The parameter naming the commit a run applies (the merge's SHA)."""
    before: str | None = None
    """The parameter naming the commit the run starts from."""
    force: str | None = None
    """The parameter that marks a forced rerun."""
    task: str | None = None
    """The parameter naming the task a run was started for, which pairs a run with a non-merge Board transition."""
