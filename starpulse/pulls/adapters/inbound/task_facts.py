"""The task actor's `TaskFacts` port: the pure derivation reads the board, the pull request store, the holder probe and
the actor's memory, and commands its effects, through the actor this adapter wraps."""

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from starpulse.board.model.feed.shared import pull_links
from starpulse.board.model.seam import HELD
from starpulse.pulls.adapters.outbound.pull_requests import landed, pull_record
from starpulse.pulls.adapters.outbound.unfinished import work_left
from starpulse.pulls.model.task_actor.derivation import Roles

if TYPE_CHECKING:
    from starpulse.pulls.adapters.inbound.task_actor import TaskActor

logger = logging.getLogger("starpulse.pulls.adapters.inbound.task_actor")

#: Seconds a judged event subject keeps its answer: a dead wait leaves Waiting at once, so a fix is seen within it.
PUBLISHER_TTL_S = 60.0


class ActorFacts:
    """`TaskFacts` over one `TaskActor`'s feed, store, probes and bookkeeping."""

    def __init__(self, actor: TaskActor) -> None:
        self._actor = actor

    @property
    def roles(self) -> Roles:
        return self._actor._feed.roles

    @property
    def board_repo(self) -> str:
        return self._actor._board_repo

    def now(self) -> float:
        return self._actor._wall()

    def record(self, url: str) -> dict[str, Any] | None:
        return self._actor._record(url)

    def own_prs(self, agent: dict[str, Any]) -> list[str]:
        return self._actor._own_prs(agent)

    def unlinked(self, agent: dict[str, Any]) -> list[str]:
        return self._actor._unlinked(agent)

    def landed(self, record: dict[str, Any]) -> bool:
        return landed(self._actor._store, record)

    def memory(self, name: str) -> Any:
        return self._actor._memory.of(name)

    def comments(self, agent: dict[str, Any]) -> list[str] | None:
        return self._actor._comments(agent)

    def dependency_needs(self, name: str) -> Sequence[str]:
        try:
            return (self._actor._read(name) or {}).get("dependencyNeeds") or ()
        except Exception as error:
            logger.warning("task actor: cannot read the dependency needs of %s: %s", name, error)
            return ()

    def unfinished(self, name: str) -> tuple[str, ...]:
        try:
            answered = self._merged_unfinished(name)
            return tuple(self._actor._unfinished(name)) if answered is None else answered
        except Exception as error:
            logger.warning("task actor: cannot read the unfinished work of %s: %s", name, error)
            return (f"the board's unfinished work cannot be read: {error}",)

    def _merged_unfinished(self, name: str) -> tuple[str, ...] | None:
        """The repositories the task modified with no merged pull request when it cites a pull request, else None."""
        actor = self._actor
        if actor._submodules is None or not actor._board_repo or not (row := actor._read(name)):
            return None
        if not (cited := pull_links(row.get("references") or ())):
            return None
        records = [pull_record(actor._store, url) for url in cited]
        parent = actor._board_repo.rsplit("/", 1)[-1]
        return tuple(work_left(row.get("modifiedFiles") or (), records, actor._submodules(), parent))

    def started(self, name: str) -> bool:
        return self._actor._started(name)

    def alive(self, name: str) -> bool | None:
        try:
            return self._actor._alive(name)
        except Exception as error:
            self._actor._unsettled = True
            logger.warning("task actor: the holder of %s was not probed: %s", name, error)
            return None

    def holds(self, name: str) -> tuple[str, ...] | None:
        return self._actor._holds_of(name)

    def owns_failure(self, name: str) -> bool:
        return self._actor._owns_failure(name)

    def settling(self, name: str) -> bool:
        return self._actor._settling == name

    def main_green(self) -> str | None:
        return self._actor._main_green() if self._actor._main_green else None

    def is_open(self, name: str) -> bool:
        return self._actor._feed.is_open(name)

    def is_done(self, name: str) -> bool:
        return self._actor._feed.is_done(name)

    def is_archived(self, name: str) -> bool:
        return self._actor._feed.is_archived(name)

    def task(self, name: str) -> dict[str, Any] | None:
        return self._actor._feed.task(name, lean=True)

    def open_tasks(self) -> list[dict[str, Any]]:
        return self._actor._feed.open_tasks()

    def machine_task(self, phase: str, name: str) -> dict[str, Any] | None:
        return self._actor._feed.machine_task(phase, name)

    def phases(self) -> list[str]:
        return sorted({phase for sequence in self._actor._sequences.values() for phase in sequence})

    def sequence(self, agent: dict[str, Any]) -> Sequence[str]:
        return self._actor._sequence(agent)

    def waiting_on(self, agent: dict[str, Any]) -> str | None:
        return self._actor._gate.waiting_on(agent)

    def heard(self, name: str) -> Sequence[str]:
        return self._actor._heard.get(name, ())

    def unpublished(self, subject: str) -> str | None:
        """Why no component publishes `subject`, else None. The board hook spawns a process, so an answer is kept for
        `PUBLISHER_TTL_S`, a failure included (it reads as published, so a fault never strands a healthy wait)."""
        actor = self._actor
        kept = actor._publisher.get(subject)
        if kept and actor._clock() < kept[1]:
            return kept[0]
        try:
            reason = actor._unpublished(subject)
        except Exception:
            logger.exception("cannot judge the publisher of %s", subject)
            reason = None
        actor._publisher[subject] = (reason, actor._clock() + PUBLISHER_TTL_S)
        return reason

    def unsettled(self) -> None:
        self._actor._unsettled = True

    def hooked(self) -> None:
        self._actor._hooked = True

    def note_hold(self, agent: dict[str, Any], reasons: tuple[str, ...], prefix: str = HELD) -> None:
        self._actor._note_hold(agent, reasons, prefix)

    def pin_held(self, name: str, on: bool) -> None:
        (self._actor._pin_held.add if on else self._actor._pin_held.discard)(name)

    def held(self, name: str, on: bool) -> None:
        (self._actor._held.add if on else self._actor._held.discard)(name)
