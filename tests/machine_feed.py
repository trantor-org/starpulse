"""A feed that draws machines the way the server does: `machine:events` is appended, the Board child's projector folds it
into `starpulse_machine_tasks`, and the feed reads the rows per request."""

from collections.abc import Mapping
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import MachineEvent, TaskKeys
from starpulse.event_log import events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.machine_engine.model.state_roles import StateRoles


class MachineFeed:
    """`put` appends one machine event to the log and folds it; `feed` reads the rows the fold wrote."""

    def __init__(
        self,
        path: Path,
        machines: Mapping[str, dict],
        *,
        window_s: float | None = None,
        keys: TaskKeys | None = None,
        roles: StateRoles | None = None,
    ) -> None:
        self.log = EventLog(f"sqlite:///{path}")
        self._projector = Projector(
            self.log.engine, EventStore(self.log.engine), log=self.log, drawn=machines, keys=keys
        )
        self.feed = BoardFeed(window_s=window_s, roles=roles, machines=machines, read_model=ReadModel(self.log.engine))

    def put(self, event: MachineEvent) -> None:
        fields = event.model_dump(mode="json", exclude_none=True, exclude={"event_id"})
        self.log.publish(machine_events.STREAM, fields)
        self.fold()

    def fold(self) -> None:
        """Fold the entries appended since the last fold, as the Board child's projector does."""
        self._projector.catch_up()

    def put_task(self, task: str, changes: dict, *, meta: dict | None = None) -> None:
        """Set a Board task's fields as a `FieldsEdited` on its stream, then fold, so the read model draws them.

        `changes` holds the read model's own fields (`state`, `title`, `labels`, `dependencies`, `assignee`); `meta`
        holds the keys the fold keeps beside them (`profile`, `impact`, `urgency`). Creates the task on first use.
        """
        store = EventStore(self.log.engine)
        event = NewEvent(
            type="FieldsEdited",
            payload={"changes": changes, "meta": meta or {}},
            actor="adin",
            writer="operator",
        )
        store.append("task", task, store.head("task", task), [event])
        self.fold()

    def put_criteria(self, task: str, criteria: list[tuple[str, bool]]) -> None:
        """Append the Task's acceptance criteria, each `(text, checked)`, as `CriterionAdded` then `CriterionChecked`."""
        store = EventStore(self.log.engine)
        events = []
        for number, (text, checked) in enumerate(criteria, start=1):
            events.append(NewEvent(type="CriterionAdded", payload={"kind": "ac", "text": text}, actor="adin", writer="operator"))
            if checked:
                payload = {"kind": "ac", "n": number, "checked": True}
                events.append(NewEvent(type="CriterionChecked", payload=payload, actor="adin", writer="operator"))
        store.append("task", task, store.head("task", task), events)
        self.fold()


def agents(feed: BoardFeed, flow: str) -> list[dict]:
    """The tasks the snapshot draws in `flow`."""
    return next(f["agents"] for f in feed.snapshot()["flows"] if f["name"] == flow)
