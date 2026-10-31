"""Workflows known only from CloudEvents pushed to `POST /api/machine-events`: their latest run, and a step graph learned from the steps reported.

A pushed workflow has no listing to read its steps from, so each step an entry names joins the graph, with the
steps it said it waits on. The graph is kept in the history store, so after a restart the workflow is drawn with
its steps, not started, until the next run reports them again. A step that has never run is not drawn.

Entries arrive on the one reader thread; the lock only keeps what `save` writes whole. The feed holds the
page-facing state, and the workflows with the cursor they reflect are saved in the event log (`resume`), so a restart
reads the entries after it rather than the whole retention.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol, get_args

from pydantic import BaseModel

from starpulse.board.board_feed import PUSHED_INSTANCE, SAVE_INTERVAL, BoardStore, InstanceRuns, entry_position
from starpulse.contracts.adapters import LAST_OUTCOMES, RunStatus
from starpulse.runs.model import run_events

__all__ = ["PUSHED_INSTANCE", "PushRuns"]

logger = logging.getLogger(__name__)


class GraphStore(Protocol):
    """Where learned steps persist: the history store."""

    def record_step(self, workflow: str, step: str, depends: list[str] | None) -> None: ...

    def learned_graphs(self) -> dict[str, dict[str, list[str]]]: ...


class PushedRunsSnapshot(BaseModel):
    """The workflows `PushRuns` saves beside the position they reflect."""

    SCHEMA_VERSION: ClassVar[int] = 2
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


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    def __init__(self, runs: InstanceRuns, store: GraphStore | None) -> None:
        self._runs = runs
        self._store = store
        self._dags = {name: _dag(name, steps) for name, steps in (store.learned_graphs() if store else {}).items()}
        self._replay_end: int | None = None
        self._lock = threading.Lock()
        #: The id of the last entry read, which `_dags` reflects, and the one last saved.
        self._seen = self._saved = 0
        self._store_at: tuple[BoardStore, str] | None = None
        self._publish()

    def _publish(self) -> None:
        self._runs.set_dags(list(self._dags.values()), None)

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Move one workflow by an entry; a malformed one, or one for a run that is not the one drawn, is dropped.

        During the startup replay the workflows are published once, at the replay's last entry: each publish rebuilds
        the feed's Ledger under its lock, which every page request waits on.
        """
        with self._lock:
            moved = self._move(fields)
            self._seen = entry_position(entry_id)
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
        (another `PushedRunsSnapshot.SCHEMA_VERSION`). The workflows are saved to `store` under `stream` from now on
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
            self._dags |= {name: dict(dag) for name, dag in snapshot.dags.items()}
            self._seen = self._saved = position
        self._publish()
        logger.warning("StarPulse: resuming %s after %s", stream, position)
        return position

    def save(self) -> None:
        """Write the workflows and the position they reflect to the store `resume` was given, unless nothing was read
        since the last save. A store that cannot be written is logged; the next save tries again."""
        if self._store_at is None:
            return
        store, stream = self._store_at
        with self._lock:
            seen, dags = (self._seen, dict(self._dags))  # a workflow is replaced, never changed in place
        if seen == self._saved:
            return
        try:
            store.save(stream, seen, PushedRunsSnapshot(dags=dags))
        except Exception as exc:  # the store is down; the workflows still draw and the next save retries
            logger.warning("StarPulse: cannot save the pushed runs of %s: %s", stream, exc)
            return
        self._saved = seen

    def keep_saved(self, stop: threading.Event, interval: float = SAVE_INTERVAL) -> None:
        """Save every `interval` seconds, and once more when `stop` is set."""
        while not stop.wait(interval):
            self.save()
        self.save()

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
            steps = [{**step, "status": "not_started"} for step in dag["steps"]] if dag else []
            self._dags[entry.key] = (dag or _dag(entry.key, {})) | {
                "status": entry.status,
                "runId": entry.run_id,
                "startedAt": _iso(entry.at),
                "finishedAt": "",
                "steps": steps,
            }
        elif dag is not None and dag["runId"] == entry.run_id:
            self._dags[entry.key] = dag | {"status": entry.status, "finishedAt": _iso(entry.at)}
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
