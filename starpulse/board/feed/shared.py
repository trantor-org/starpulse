"""Feed constants, helpers and the protocols the feed's other modules share."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from starpulse.board import criteria
from starpulse.board.model.markdown import needs_attention_reason
from starpulse.contracts.adapters import BoardTask
from starpulse.machine_engine.model.machine_definition import Writer
from starpulse.machine_engine.model.transitions import board_moves, lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from pydantic import BaseModel


#: Whether a restart resends this `/api/events` kind. Only `snapshot`: a reconnecting page needs the Board
#: the replay built. Every other kind is a delta of that Board, so resending it would make consumers act twice.
FEED_EVENT_RESEND = {
    "snapshot": True,
    "task": False,
    "move": False,
    "pulls": False,
    "claim": False,
    "verdict": False,
    "dags": False,
    "ledgers": False,
    "scheduler": False,
}

# The feed's name, not this module's: operators and trantor's tests filter the feed's records by it.
logger = logging.getLogger("starpulse.board.board_feed")

_PULL_REQUEST = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+/?")

# The runs instance pushed workflows belong to, so the page names them `pushed/<workflow>`.
PUSHED_INSTANCE = "pushed"

#: How often a running reader saves the Board, in seconds; a restart reads again what arrived since.
SAVE_INTERVAL = 60.0

#: Seconds between passes that evaluate the Start Criteria of the Waiting tasks, as long as the evaluator caches a result.
CRITERIA_INTERVAL = criteria.CACHE_SECONDS

#: How far back a task's entry into a lane is an occurrence a run can pair with, in seconds: as far as a tied workflow's recent runs reach.
LEDGER_WINDOW = 86400.0

#: How many published changes the feed keeps for a page connecting on a snapshot older than the feed.
_SENT_LOG = 512


def pull_links(references: Iterable[str]) -> list[str]:
    """The pull request links among `references`."""
    return [ref for ref in references if _PULL_REQUEST.fullmatch(ref)]


def cited_pulls(task: BoardTask) -> list[str]:
    """The pull request links among the task's references."""
    return pull_links(task.references)


def _midnight(at: float) -> float:
    """The start of the local day `at` falls in, in epoch seconds."""
    return datetime.fromtimestamp(at).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def is_cold(agent: dict) -> bool:
    """Whether the agent is a cold done task: its id, state, entered time and moves, with the record left on the Board."""
    return "title" not in agent


def cooled(agent: dict, clock: Callable[[], float], done: str | None) -> dict:
    """The agent, or its cold stub when it entered the `done` state before local midnight by `clock`; the stub keeps
    its moves, so a reopen is still offered."""
    if agent["state"] == done and agent["entered"] < _midnight(clock()):
        return {"id": agent["id"], "state": agent["state"], "entered": agent["entered"], "moves": agent.get("moves", {})}
    return agent


def task_agent(task: BoardTask) -> dict:
    """One task as an agent on the Board machine, its lane as the state id."""
    ticks = task.acceptance_checked + (False,) * len(
        task.acceptance_criteria
    )  # a criterion past the ticks is unchecked
    return {
        "id": task.id,
        "title": task.title,
        "state": task.lane,
        "model": task.profile,
        "profile": task.profile,
        "assignee": task.assignee,
        "labels": list(task.labels),
        "milestone": task.milestone,
        "impact": task.impact,
        "urgency": task.urgency,
        "adr_needed": task.adr_needed,
        "duplicate_search": task.duplicate_search,
        "duplicate_resolution": task.duplicate_resolution,
        "type": task.type,
        "dependencies": list(task.dependencies),
        "prs": cited_pulls(task),
        "runs": [],
        "description": task.description,
        "criteria": [{"text": text, "checked": checked} for text, checked in zip(task.acceptance_criteria, ticks)],
        "pause_reason": task.pause_reason,
        "readable": task.readable,
        "moves": {column: move.model_dump() for column, move in task.moves.items()},
        "created": task.created_at,
    }


def read_model_lane_moves(machine: dict) -> dict[str, dict[str, dict]]:
    """The Board machine's moves out of each lane, as dumps a read-model agent carries, keyed by source lane id."""
    writers = {
        event: tuple(Writer(**writer) for writer in declared) for event, declared in machine.get("writers", {}).items()
    }
    return {
        source: {target: move.model_dump() for target, move in moves.items()}
        for source, moves in board_moves(machine, writers).items()
    }


def summary_agent(summary: Mapping[str, Any], workable: bool = False, moves: Mapping[str, Any] = {}) -> dict:
    """One read-model summary as an agent on the Board machine: what a card draws; the record is `/api/task/<id>`.

    A workable Task is workable since it last changed: the read model keeps no finer date. Its profile is the one the
    fold keeps in `meta`, as a held Task's is its own.
    """
    profile = (summary.get("meta") or {}).get("profile") or None
    return {
        "id": summary["id"],
        "title": summary["title"],
        "state": lane_id(summary["state"]),
        "model": profile or "",
        "profile": profile,
        "assignee": summary["assignee"],
        "released": summary["released"],
        "labels": list(summary["labels"]),
        "milestone": summary["milestone"],
        "type": summary["type"],
        "dependencies": list(summary.get("dependencies", ())),
        "prs": [],
        "runs": [],
        "description": "",
        "criteria": [],
        "pause_reason": None,
        "moves": dict(moves),
        "created": summary["updated_at"],
        "entered": summary["updated_at"],
        "workable": workable,
        "workable_since": summary["updated_at"] if workable else None,
    }


def read_model_detail(row: Mapping[str, Any], attention: str | None = None) -> dict:
    """The fields a summary leaves out that a Task's record draws: its pull requests, description, criteria,
    Definition of Done items and, in the `attention` lane, the reason its description's Needs attention section gives."""
    acceptance = [item for item in row["criteria"] if item["kind"] == "ac"]
    done = [item for item in row["criteria"] if item["kind"] == "dod"]
    waits_on_person = attention is not None and lane_id(row["state"]) == lane_id(attention)
    return {
        "prs": pull_links(row["references"]),
        "description": row["description"],
        "criteria": [{"text": item["text"], "checked": item["checked"]} for item in acceptance],
        "definition_of_done": [{"text": item["text"], "checked": item["checked"]} for item in done],
        "pause_reason": needs_attention_reason(row["description"]) if waits_on_person else "",
    }


def _cold_stub(summary: Mapping[str, Any]) -> dict:
    return {"id": summary["id"], "state": lane_id(summary["state"]), "entered": summary["updated_at"]}


def settled_entry(task: BoardTask) -> dict | None:
    """Where a settled task settled, when, and the title, assignee, milestone and labels it settled with; None for an
    open task."""
    if not task.settled:
        return None
    return {
        "state": task.settled,
        "at": task.settled_at,
        "created": task.created_at,
        "title": task.title,
        "model": task.profile,
        "milestone": task.milestone,
        "labels": list(task.labels),
    }


def entry_position(entry_id: str) -> int:
    """The log id of an entry id, `7` or the `7-0` a stream of the retired Redis form named it."""
    return int(entry_id.partition("-")[0])


class LaneRecorder(Protocol):
    """Where a feed keeps each lane change it applies, idempotent on the event id (`HistoryStore`)."""

    def record_lane(
        self, event_id: str, task: str, status: str, at: float, *, event: Mapping[str, Any] | None = None
    ) -> bool | None:
        """Keep one lane change, and with it the lane `event` (the `board:lanes` fields) in the same transaction; True
        when it wrote a row, False for a repeat of the task's last lane or a known id."""


class TaskIndex(Protocol):
    """Where the feed keeps each task's searchable text (`search.SearchIndex`)."""

    def index(self, task: BoardTask, finished_at: float | None = None) -> None: ...

    def remove(self, task_id: str) -> None: ...


class BoardStore(Protocol):
    """Where a feed keeps the Board it saved: the event log's `Checkpoints`, or any store that holds one per name."""

    def load(self, name: str, model: type[BaseModel] | None = None) -> tuple[int | None, BaseModel | None]: ...

    def save(self, name: str, position: int, model: BaseModel | None = None, *, conn: Any = None) -> None: ...


class CriteriaStore(Protocol):
    """Where the feed keeps when each task's Start Criteria were first seen all met (`HistoryStore`)."""

    def criteria_met(self) -> dict[str, float]: ...

    def save_criteria_met(self, met: dict[str, float]) -> None: ...


class ExpiriesStore(Protocol):
    """Where the claim-TTL sweep keeps each held working task's claim expiry from its latest pass (`HistoryStore`)."""

    def claim_expiries(self) -> dict[str, float]: ...

    def save_claim_expiries(self, expiries: dict[str, float]) -> None: ...
