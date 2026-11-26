"""The UUID every board item stores beside its key: a v7 minted at create. A Task that existed before a UUID was stored
has the v5 of its board and key, which revision 0074 stamps into its History."""

import uuid

from starpulse.board.adapters.task_history import KIND, WRITER
from starpulse.board.model.seam import OPERATOR
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion


def mint() -> str:
    return str(uuid.uuid7())


def stamp_task(store: EventStore, task: str, minted: str) -> bool:
    """Append one `FieldsEdited` carrying `minted` to `task`'s stream unless it has a UUID; whether it did. A stream whose
    head moved since the read (a concurrent append) is read again."""
    while events := store.read(KIND, task):
        if replay(events).get("meta", {}).get("uuid"):
            return False
        try:
            store.append(KIND, task, events[-1].version, [NewEvent("FieldsEdited", {"meta": {"uuid": minted}}, OPERATOR, WRITER)])
        except StaleVersion:
            continue
        return True
    return False
