"""The Runs context's config section: each `[[runs]]` instance and each `[[producers]]` system that posts CloudEvents."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from starpulse.board.model.commit_keys import CommitKeys

#: The most events one CloudEvents batch may hold.
MAX_BATCH = 200


@dataclass(frozen=True)
class RunsInstance:
    """One configured runs adapter: the workflows it lists are shown as `<name>/<workflow>`."""

    name: str
    type: str | None
    """The adapter module that reads the instance: a name under `starpulse`, or a dotted module path; none: a push-only instance."""
    url: str | None
    """What the adapter reads; none with no type."""
    run_safe: tuple[str, ...] = ()
    """The workflows Run now may start; any other answers 404, so none is startable by default."""
    domains: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """The page's groups of this instance's workflows, in the order it lays them out; a nested domain lists its workflows name-sorted."""
    processes: Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]] = field(default_factory=dict)
    """Each domain's ordered `(process, workflows)` packages; an empty tuple is a flat domain."""
    commit: CommitKeys | None = None
    """The `[runs.commit]` table; none: a run pairs with a merge only by the time it started."""


@dataclass(frozen=True)
class Producer:
    """A system that posts machine events as CloudEvents; `token_env` names the variable holding its token, and it may
    write only the `machines` and `actors` named here."""

    name: str
    token_env: str
    machines: tuple[str, ...]
    actors: tuple[str, ...]
    adapter: str | None = None
    """A run Adapter type (`[[runs]]` `type`) whose own status labels this producer's Step events carry; the ingest reads
    each through that adapter's `status_of`, so a hook posts its system's label as it is."""
