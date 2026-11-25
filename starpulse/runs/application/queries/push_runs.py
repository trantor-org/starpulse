"""Workflows known only from CloudEvents pushed to the ingest: their latest run, and a step graph learned from the steps reported.

A pushed workflow has no listing to read its steps from, so each step an entry names joins the graph, with the
steps it said it waits on. The graph is kept in the history store, so after a restart the workflow is drawn with
its steps, not started, until the next run reports them again. A step that has never run is not drawn.

Entries arrive on the one reader thread; the lock only keeps what `save` writes whole. The feed holds the
page-facing state, and the workflows with the cursor they reflect are saved in the event log (`resume`), so a restart
reads the entries after it rather than the whole retention.
"""

import logging
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Protocol, get_args

from pydantic import BaseModel

from starpulse.board.model.board_feed import PUSHED_INSTANCE, SAVE_DEBOUNCE, BoardStore, InstanceRuns, entry_position
from starpulse.contracts.adapters import LAST_OUTCOMES, RunStatus
from starpulse.contracts.stamps import iso_utc
from starpulse.event_log.wake import StopEvent, save_on_change
from starpulse.runs.model import run_events

__all__ = ["PUSHED_INSTANCE", "PushRuns"]

logger = logging.getLogger(__name__)


class GraphStore(Protocol):
    """Where learned steps persist: the history store."""

    def record_step(self, workflow: str, step: str, depends: list[str] | None) -> None: ...

    def learned_graphs(self) -> dict[str, dict[str, list[str]]]: ...

    def forget_workflow(self, workflow: str) -> None: ...


class PushedRunsSnapshot(BaseModel):
    """The workflows `PushRuns` saves beside the position they reflect."""

    dags: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _Entry:
    """One decoded `runs:events` entry."""

    event: str
    workflow: str
    run_id: str
    status: str
    at: float
    step: str | None
    depends: list[str] | None
    instance: str | None = None

    @property
    def key(self) -> str:
        """The workflow's name here: an ingested one is `<instance>/<workflow>`, so two instances never share one."""
        return f"{self.instance}/{self.workflow}" if self.instance else self.workflow


def _decode(fields: dict) -> _Entry | None:
    """The entry the contract allows, or None for one it does not."""
    try:
        step = fields.get("step") or None
        depends = fields["depends"] if step and "depends" in fields else None
        entry = _Entry(
            fields["event"],
            fields["workflow"],
            fields["run_id"],
            fields["status"],
            float(fields["time"]),
            step,
            depends,
            fields.get("instance") or None,
        )
    except KeyError, ValueError, TypeError:
        return None
    well_formed = depends is None or isinstance(depends, list) and all(isinstance(d, str) for d in depends)
    return entry if entry.event in run_events.EVENTS and entry.status in get_args(RunStatus) and well_formed else None


#: The statuses of a step that is not over.
_UNSETTLED = {"not_started", "queued", "running"}


def _step(name: str, depends: list[str], status: str, last: list[str] | None = None) -> dict[str, Any]:
    """A step as pushed: a pushed run declares no precondition or lock, so only its outcomes in `last` are kept."""
    return {
        "name": name,
        "depends": depends,
        "status": status,
        "kind": None,
        "precondition": None,
        "lock": None,
        "last": last or [],
    }


def _outcomes(step: dict, status: str) -> list[str]:
    """The step's `last` once it reports `status`: an outcome joins at the front, replacing the one this run already reported."""
    if status in _UNSETTLED:
        return step["last"]
    kept = step["last"] if step["status"] in _UNSETTLED else step["last"][1:]
    return [status, *kept][:LAST_OUTCOMES]


def _dag(name: str, steps: dict[str, list[str]]) -> dict[str, Any]:
    """A workflow with no run yet, drawn with the steps it has learned."""
    return {
        "name": name,
        "status": "not_started",
        "runId": "",
        "startedAt": "",
        "finishedAt": "",
        "steps": [_step(step, depends, "not_started") for step, depends in steps.items()],
        "schedule": [],
        "stats": None,
        "rerun": None,
    }


class PushRuns:
    """The pushed workflows as the page draws them, moved by `runs:events` entries."""

    def __init__(
        self,
        runs: InstanceRuns,
        store: GraphStore | None,
        retention: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._retention = retention
        self._clock = clock
        self._runs = runs
        self._store = store
        self._dags = {name: _dag(name, steps) for name, steps in (store.learned_graphs() if store else {}).items()}
        self._replay_end: int | None = None
        self._configured: Collection[str] | None = None
        self._lock = threading.Lock()
        self._publishing = threading.Lock()  # one publish at a time, each reading the workflows as they stand then
        self._pruned = 0  # prunes so far, which a save in flight compares to see its copy is no longer current
        #: The id of the last entry read, which `_dags` reflects, and the one last saved.
        self._seen = self._saved = 0
        #: Set by every entry read and every prune, for `keep_saved`.
        self._unsaved = threading.Event()
        self._store_at: tuple[BoardStore, str] | None = None
        self._publish()

    def _expire(self) -> None:
        """Drop the workflows whose last run started or ended longer ago than the retention: the log no longer holds
        their entries, so nothing can move them again. A workflow with no run keeps its learned steps."""
        if self._retention is None:
            return
        floor = iso_utc(self._clock() - self._retention)
        with self._lock:
            old = [name for name, dag in self._dags.items() if (dag["finishedAt"] or dag["startedAt"] or floor) < floor]
        self._drop(old)

    def drop_unconfigured(self, instances: Collection[str]) -> None:
        """Drop the workflows named `<instance>/<workflow>` whose instance is not in `instances`, with their learned
        steps: a retired producer never pushes again. A bare name is no instance's to drop. `resume` drops again, as
        the saved workflows it restores may name a retired one."""
        self._configured = instances
        with self._lock:
            old = [name for name in self._dags if "/" in name and name.split("/", 1)[0] not in instances]
        self._drop(old)
        if old:
            self._publish()

    def _drop(self, old: list[str]) -> None:
        if not old:
            return
        with self._lock:
            for name in old:
                del self._dags[name]
            self._pruned += 1
            self._saved = -1
        self._unsaved.set()
        for name in old:
            if self._store:  # else a restart draws it again from its learned steps
                try:
                    self._store.forget_workflow(name)
                except Exception as exc:  # the store is down; the workflow is dropped from the page all the same
                    logger.warning("StarPulse: cannot forget the learned steps of %s: %s", name, exc)

    def _publish(self) -> None:
        self._expire()
        with self._publishing:
            self._runs.set_dags(list(self._dags.values()), None)

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Move one workflow by an entry; a malformed one, or one for a run that is not the one drawn, is dropped.

        During the startup replay the workflows are published once, at the replay's last entry: each publish rebuilds
        the feed's Ledger under its lock, which every page request waits on.
        """
        with self._lock:
            moved = self._move(fields)
            self._seen = entry_position(entry_id)
        self._unsaved.set()
        if self._replay_end is None:
            if moved:
                self._publish()
        elif entry_position(entry_id) >= self._replay_end:
            self._replay_end = None
            self._publish()

    def resume(self, store: BoardStore, stream: str, retained: Callable[[int], bool]) -> int | None:
        """Restore the workflows `store` saved for `stream` and return the position to read the stream after, else None.

        None means the reader replays what the stream retains: nothing was saved, `retained(position)` says the stream
        no longer holds every entry after the saved position, or the saved state is not one this reader can read
        (it no longer validates as a `PushedRunsSnapshot`). The workflows are saved to `store` under `stream` from now on
        (`save`, `keep_saved`).
        """
        self._store_at = (store, stream)
        position, snapshot = store.load(stream, PushedRunsSnapshot)
        if position is None:
            logger.warning("StarPulse: replaying %s: no saved pushed runs", stream)
            return None
        if not retained(position):
            logger.warning("StarPulse: replaying %s: cursor %s is no longer retained", stream, position)
            return None
        if snapshot is None:
            logger.warning("StarPulse: replaying %s: the saved pushed runs cannot be read", stream)
            return None
        with self._lock:
            # a workflow saved before `rerun` joined the `Dag` contract lacks it, and the page refuses the whole instance
            self._dags |= {name: {"rerun": None, **dag} for name, dag in snapshot.dags.items()}
            self._seen = self._saved = position
        if self._configured is not None:
            self.drop_unconfigured(self._configured)
        self._publish()
        logger.warning("StarPulse: resuming %s after %s", stream, position)
        return position

    def prune(self, instance: str, listed: Collection[str]) -> None:
        """Drop the workflows named `<instance>/<workflow>` whose workflow `instance` no longer lists. A bare name is
        no instance's to drop, and an empty listing is no evidence a workflow is gone."""
        prefix = f"{instance}/"
        with self._lock:
            gone = [name for name in self._dags if name.startswith(prefix) and name[len(prefix) :] not in listed]
            if not listed or not gone:
                return
            for name in gone:
                del self._dags[name]
            self._pruned += 1
            self._saved = -1  # the saved snapshot still holds them; the next save writes this state at the same position
        self._unsaved.set()
        self._publish()

    def save(self) -> None:
        """Write the workflows and the position they reflect to the store `resume` was given, unless nothing was read
        since the last save. A store that cannot be written is logged and the save is armed again."""
        if self._store_at is None:
            return
        store, stream = self._store_at
        with self._lock:
            seen, dags, pruned = (self._seen, dict(self._dags), self._pruned)  # a workflow is replaced, never changed in place
        if seen == self._saved:
            return
        try:
            store.save(stream, seen, PushedRunsSnapshot(dags=dags))
        except Exception as exc:  # the store is down; the workflows still draw and the next debounce retries
            logger.warning("StarPulse: cannot save the pushed runs of %s: %s", stream, exc)
            self._unsaved.set()
            return
        with self._lock:
            if self._pruned == pruned:  # a prune since the copy left the saved state behind; the next save writes it
                self._saved = seen

    def keep_saved(self, stop: StopEvent, debounce: float = SAVE_DEBOUNCE) -> None:
        """Save `debounce` seconds after an entry or a prune, and once more when `stop` is set."""
        save_on_change(stop, self._unsaved, self.save, debounce)

    def _move(self, fields: dict) -> bool:
        """Apply an entry to the workflow it names; whether it moved one."""
        entry = _decode(fields)
        if entry is None:
            return False
        dag = self._dags.get(entry.key)
        if entry.step is not None:
            if dag is None or dag["runId"] != entry.run_id:
                return False
            self._report_step(dag, entry.step, entry.depends, entry.status)
        elif entry.event == "StepStarted":
            if dag is not None and dag["runId"] == entry.run_id and dag["status"] not in _UNSETTLED:
                return False  # its own end was read first: the run stays ended
            steps = [{**step, "status": "not_started"} for step in dag["steps"]] if dag else []
            self._dags[entry.key] = (dag or _dag(entry.key, {})) | {
                "status": entry.status,
                "runId": entry.run_id,
                "startedAt": iso_utc(entry.at),
                "finishedAt": "",
                "steps": steps,
            }
        elif dag is not None and dag["runId"] == entry.run_id:
            self._dags[entry.key] = dag | {"status": entry.status, "finishedAt": iso_utc(entry.at)}
        else:
            return False  # the end of a run that is no longer the one drawn
        return True

    def _report_step(self, dag: dict, name: str, depends: list[str] | None, status: str) -> None:
        """Set a step's status and, when the entry names them, its dependencies; a step not yet known joins the graph."""
        if self._store:
            self._store.record_step(dag["name"], name, depends)
        steps = [
            {
                **step,
                "status": status,
                "last": _outcomes(step, status),
                **({} if depends is None else {"depends": depends}),
            }
            if step["name"] == name
            else step
            for step in dag["steps"]
        ]
        if all(step["name"] != name for step in steps):
            steps.append(_step(name, depends or [], status, [] if status in _UNSETTLED else [status]))
        # a new dict: the feed compares what it was given before with what it is given now
        self._dags[dag["name"]] = {**dag, "steps": steps}

    def await_stream(self) -> None:
        """Nothing to say: pushed workflows are not part of the page's ready state (`follow` calls this)."""

    def expect(self, last_id: str) -> None:
        """Hold publishing until the replay reaches `last_id`, the stream's last entry at start (`follow` calls this)."""
        if entry_position(last_id) > self._seen:
            self._replay_end = entry_position(last_id)
