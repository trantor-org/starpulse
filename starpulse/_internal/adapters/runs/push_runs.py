"""Workflows known only from `starpulse emit`: their latest run, and a step graph learned from the steps reported.

A pushed workflow has no listing to read its steps from, so each step an entry names joins the graph, with the
steps it said it waits on. The graph is kept in the history store, so after a restart the workflow is drawn with
its steps, not started, until the next run reports them again. A step that has never run is not drawn.

Entries arrive on the one reader thread, so nothing here needs a lock; the feed holds the page-facing state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, get_args

from starpulse._internal.adapters.runs import run_events
from starpulse.contracts.adapters import RunStatus
from starpulse._internal.feed.board_feed import PUSHED_INSTANCE, InstanceRuns, stream_id

__all__ = ["PUSHED_INSTANCE", "PushRuns"]


class GraphStore(Protocol):
    """Where learned steps persist: the history store."""

    def record_step(self, workflow: str, step: str, depends: list[str] | None) -> None: ...

    def learned_graphs(self) -> dict[str, dict[str, list[str]]]: ...


@dataclass(frozen=True)
class _Entry:
    """One decoded `runs:events` entry."""

    phase: str
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
            fields["phase"],
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
    return entry if entry.phase in run_events.PHASES and entry.status in get_args(RunStatus) and well_formed else None


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _step(name: str, depends: list[str], status: str) -> dict[str, Any]:
    return {"name": name, "depends": depends, "status": status, "kind": None}


def _dag(name: str, steps: dict[str, list[str]]) -> dict[str, Any]:
    """A workflow with no run yet, drawn with the steps it has learned."""
    return {
        "name": name,
        "status": "not_started",
        "runId": "",
        "startedAt": "",
        "finishedAt": "",
        "steps": [_step(step, depends, "not_started") for step, depends in steps.items()],
    }


class PushRuns:
    """The pushed workflows as the page draws them, moved by `runs:events` entries."""

    def __init__(self, runs: InstanceRuns, store: GraphStore | None) -> None:
        self._runs = runs
        self._store = store
        self._dags = {name: _dag(name, steps) for name, steps in (store.learned_graphs() if store else {}).items()}
        self._replay_end: tuple[int, int] | None = None
        self._publish()

    def _publish(self) -> None:
        self._runs.set_dags(list(self._dags.values()), None)

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Move one workflow by an entry; a malformed one, or one for a run that is not the one drawn, is dropped.

        During the startup replay the workflows are published once, at the replay's last entry: each publish rebuilds
        the feed's Ledger under its lock, which every page request waits on.
        """
        moved = self._move(fields)
        if self._replay_end is None:
            if moved:
                self._publish()
        elif stream_id(entry_id) >= self._replay_end:
            self._replay_end = None
            self._publish()

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
        elif entry.phase == "start":
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
            {**step, "status": status, **({} if depends is None else {"depends": depends})}
            if step["name"] == name
            else step
            for step in dag["steps"]
        ]
        if all(step["name"] != name for step in steps):
            steps.append(_step(name, depends or [], status))
        # a new dict: the feed compares what it was given before with what it is given now
        self._dags[dag["name"]] = {**dag, "steps": steps}

    def await_stream(self) -> None:
        """Nothing to say: pushed workflows are not part of the page's ready state (`follow` calls this)."""

    def expect(self, last_id: str) -> None:
        """Hold publishing until the replay reaches `last_id`, the stream's last entry at start (`follow` calls this)."""
        if stream_id(last_id) > (0, 0):
            self._replay_end = stream_id(last_id)
