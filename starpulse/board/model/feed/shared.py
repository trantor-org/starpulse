"""Feed constants, helpers and the protocols the feed's other modules share."""

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from starpulse.board.model.entry import default_profile
from starpulse.board.model.markdown import needs_attention_reason
from starpulse.contracts.adapters import DEFAULT_TIER
from starpulse.machine_engine.model.machine_definition import Writer
from starpulse.machine_engine.model.transitions import board_moves, lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from pydantic import BaseModel


#: Whether a restart resends this feed kind. Only `snapshot`: a reconnecting page needs the Board
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

# The feed's name, not this module's: operators and a host project's tests filter the feed's records by it.
logger = logging.getLogger("starpulse.board.model.board_feed")

# The runs instance pushed workflows belong to, so the page names them `pushed/<workflow>`.
PUSHED_INSTANCE = "pushed"

#: How long a running reader waits after a change before it saves the Board, in seconds, so a burst is one save; a
#: restart reads again what arrived since.
SAVE_DEBOUNCE = 10.0

#: How far back a task's entry into a lane is an occurrence a run can pair with, in seconds: as far as a tied workflow's recent runs reach.
LEDGER_WINDOW = 86400.0


#: The link roles that tie a pull request to a task: `delivers` the one it ships through, `cites` any other it names.
LINKED = ("delivers", "cites")
DELIVERS = ("delivers",)


def local_midnight(at: float) -> float:
    """The start of the local day `at` falls in, in epoch seconds."""
    return datetime.fromtimestamp(at).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


#: How long a Done Task stays in the snapshot, with its jobs and machine instances, after it finishes.
LIVE_WINDOW_S = 24 * 3600


def read_model_lane_moves(machine: dict) -> dict[str, dict[str, dict]]:
    """The Board machine's moves out of each lane, as dumps a read-model agent carries, keyed by source lane id."""
    writers = {
        event: tuple(Writer(**writer) for writer in declared) for event, declared in machine.get("writers", {}).items()
    }
    return {
        source: {target: move.model_dump() for target, move in moves.items()}
        for source, moves in board_moves(machine, writers).items()
    }


def summary_agent(
    summary: Mapping[str, Any],
    workable: bool = False,
    moves: Mapping[str, Any] = {},
    defaults: Mapping[str, Mapping[str, str]] = {},
) -> dict:
    """One read-model summary as an agent on the Board machine: what a card draws; the record is `/api/task/<id>`.

    A workable Task is workable since it last changed: the read model keeps no finer date. Its profile is the one the
    fold keeps in `meta`, as a held Task's is its own; a Task with none draws the board's `defaults` for its labels.
    """
    meta = summary.get("meta") or {}
    profile = meta.get("profile") or default_profile(summary.get("labels") or [], defaults)
    return {
        "id": summary["id"],
        "title": summary["title"],
        "state": lane_id(summary["state"]),
        "model": profile or "",
        "profile": profile,
        "impact": meta.get("impact", ""),
        "urgency": meta.get("urgency", ""),
        "tier": meta.get("tier") or DEFAULT_TIER,
        "source": meta.get("source", ""),
        "follows": meta.get("follows", ""),
        "frozen": dict(meta["frozen"]) if meta.get("frozen") else None,
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


_DONE_DOT = ("id", "title", "state", "model", "labels", "milestone", "type", "follows", "created", "entered")


def done_dot(agent: dict) -> dict:
    """A Done task as the snapshot and its deltas carry it: what the Star Map and the counts draw, none of the record."""
    return {key: agent[key] for key in _DONE_DOT if key in agent}


def settled_entry(summary: Mapping[str, Any], defaults: Mapping[str, Mapping[str, str]] = {}) -> dict:
    """An archived Done task as the snapshot's `settled` carries it: the read model keeps only when it last changed, so
    that is when it settled, and it has no creation date."""
    agent = summary_agent(summary, defaults=defaults)
    return {
        "state": agent["state"],
        "at": summary["updated_at"],
        "created": None,
        "title": agent["title"],
        "model": agent["model"],
        "milestone": agent["milestone"],
        "labels": agent["labels"],
    }


def read_model_detail(row: Mapping[str, Any], attention: str | None = None, links: Sequence[tuple[str, str]] = ()) -> dict:
    """The fields a summary leaves out that a Task's record draws: its pull requests (`prs`, the pages of its links), description, criteria,
    Definition of Done items and, in the `attention` lane, the reason its description's Needs attention section gives."""
    acceptance = [item for item in row["criteria"] if item["kind"] == "ac"]
    done = [item for item in row["criteria"] if item["kind"] == "dod"]
    waits_on_person = attention is not None and lane_id(row["state"]) == lane_id(attention)
    return {
        "prs": list(dict.fromkeys(url for _, url in links)),
        "delivered": list(dict.fromkeys(url for role, url in links if role in DELIVERS)),
        "description": row["description"],
        "criteria": [{"text": item["text"], "checked": item["checked"]} for item in acceptance],
        "definition_of_done": [{"text": item["text"], "checked": item["checked"]} for item in done],
        "pause_reason": needs_attention_reason(row["description"]) if waits_on_person else "",
    }


def _cold_stub(summary: Mapping[str, Any]) -> dict:
    record = {
        "title": summary["title"],
        "profile": (summary.get("meta") or {}).get("profile") or "",
        "labels": list(summary["labels"]),
        "milestone": summary["milestone"],
        "type": summary["type"],
        "follows": (summary.get("meta") or {}).get("follows", ""),
    }
    return {"id": summary["id"], "state": lane_id(summary["state"]), "entered": summary["updated_at"], "record": record}


def entry_position(entry_id: str) -> int:
    """The log id of an entry id, `7` or the `7-0` a stream of the retired Redis form named it."""
    return int(entry_id.partition("-")[0])


class LaneRecorder(Protocol):
    """Where a feed keeps each lane change it applies, idempotent on the event id (`HistoryStore`)."""

    def record_lane(
        self,
        event_id: str,
        task: str,
        status: str,
        at: float,
        *,
        event: Mapping[str, Any] | None = None,
        connection: Any = None,
    ) -> bool | None:
        """Keep one lane change, and with it the lane `event` (the `board:lanes` fields) in the same transaction, the
        caller's `connection` when given; True when it wrote a row, False for a repeat of the task's last lane or a known id."""


class BoardStore(Protocol):
    """Where a feed keeps the Board it saved: the event log's `Checkpoints`, or any store that holds one per name."""

    def load(self, name: str, model: type[BaseModel] | None = None) -> tuple[int | None, BaseModel | None]: ...

    def save(self, name: str, position: int, model: BaseModel | None = None, *, conn: Any = None) -> None: ...
