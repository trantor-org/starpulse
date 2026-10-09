"""An IC's forwarder against a real hub over HTTP: exactly-once history, names that stay home, tokens that gate.

The IC is a SQLite file with its own store; the hub is `/api/forward` on a running server whose event log is a SQLite
file or a Postgres database. The forwarder's transport is the real `post`, wrapped to record what crossed the wire and
to cut the IC off at chosen points.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.runs.ingest import ForwardIngest
from starpulse._internal.hub import forward
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.hub.forward import OPT_IN_FILE, Forwarder, OptIn, post
from starpulse.contracts import BoardTask
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.config.config import Forward
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import HistoryStore

TOKEN = "ana-secret"
ASSIGNEE = "bob-the-assignee"


class Killed(BaseException):
    """The IC's process dying: not an `Exception`, so nothing in the forwarder swallows it."""


class Wire:
    """The forwarder's transport: the real `post`, recording each request and answer, with cuts on demand."""

    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        self.statuses: list[int] = []
        self.attempts = 0
        self.down = False
        self.die_after_send = False

    def __call__(self, address: str, token: str, body: bytes) -> tuple[int, dict[str, Any]]:
        self.attempts += 1
        if self.down:
            raise ConnectionRefusedError("hub unreachable")
        self.bodies.append(body)
        status, answer = post(address, token, body)
        self.statuses.append(status)
        if self.die_after_send:
            self.die_after_send = False
            raise Killed
        return status, answer


class Kit:
    def __init__(self, tmp_path: Path, hub_log: EventLog, hub_url: str) -> None:
        self.config = tmp_path / "starpulse.toml"
        self.ic_url = f"sqlite:///{tmp_path / 'ic.sqlite'}"
        self.ic_log = EventLog(self.ic_url)
        self.hub_log = hub_log
        self.feed = BoardFeed(clock=lambda: 1.0)
        self.feed.record_lanes(HistoryStore(self.ic_url, {}), self.ic_log)
        self.forward = Forward(hub_url, "HUB_TOKEN", 3)
        self.wire = Wire()
        self.opt_in = OptIn(tmp_path / OPT_IN_FILE)

    def move(self, task: str) -> None:
        """A real lane change: the Board feed places the task and appends the entry beside the history's row."""
        self.feed.put(BoardTask(id=task, team="demo", title=f"title of {task}", lane="in_progress", assignee=ASSIGNEE))

    def forwarder(self, token: str = TOKEN) -> Forwarder:
        """A forwarder as a restarted process builds it: a new store connection, nothing remembered."""
        store = HistoryStore(self.ic_url, {})
        return Forwarder(self.ic_log, store, self.forward, token, self.opt_in, send=self.wire)

    def cursor(self) -> int | None:
        return HistoryStore(self.ic_url, {}).cursor(f"forward:{self.forward.url}")

    def drain(self, forwarder: Forwarder) -> None:
        while forwarder.step():
            pass

    def at_the_ic(self) -> list[str]:
        return [e.event_id for e in Tail(self.ic_log, lane_events.STREAM).poll()]

    def at_the_hub(self) -> list[Any]:
        return Tail(self.hub_log, lane_events.STREAM).poll()


def _kit(tmp_path: Path, hub_log: EventLog, **ingest: Any) -> Iterator[Kit]:
    with serve(tmp_path / "hub", forward=ForwardIngest({"ana": TOKEN}, hub_log, **ingest)) as server:
        yield Kit(tmp_path, hub_log, url(server, ""))


@pytest.fixture
def kit(tmp_path: Path, database_url: str) -> Iterator[Kit]:
    (tmp_path / "hub").mkdir()
    yield from _kit(tmp_path, EventLog(database_url))


@pytest.fixture
def aggregates_kit(tmp_path: Path, database_url: str) -> Iterator[Kit]:
    (tmp_path / "hub").mkdir()
    yield from _kit(tmp_path, EventLog(database_url), aggregates_only=True)


def test_a_forwarder_killed_after_the_hub_wrote_a_batch_resumes_with_no_duplicate_and_no_gap(kit: Kit) -> None:
    for n in range(8):
        kit.move(f"T-{n}")
    first = kit.forwarder()
    assert first.step() == 3
    saved = kit.cursor()
    assert saved == 3

    kit.wire.die_after_send = True
    with pytest.raises(Killed):
        first.step()  # the hub has written the second batch; the IC never heard it answer

    assert len(kit.at_the_hub()) == 6
    assert kit.cursor() == saved  # persisted in the IC store, and not moved by a send nobody acknowledged
    kit.drain(kit.forwarder())

    stored = [e.event_id for e in kit.at_the_hub()]
    assert stored == [f"ana/{event_id}" for event_id in kit.at_the_ic()]
    assert kit.cursor() == 8


def test_a_restart_after_every_batch_still_delivers_each_event_once(kit: Kit) -> None:
    for n in range(7):
        kit.move(f"T-{n}")

    while kit.forwarder().step():
        pass

    assert [e.event_id for e in kit.at_the_hub()] == [f"ana/{i}" for i in kit.at_the_ic()]


def test_a_batch_sent_again_after_a_lost_answer_adds_nothing(kit: Kit) -> None:
    for n in range(3):
        kit.move(f"T-{n}")
    forwarder = kit.forwarder()
    kit.wire.die_after_send = True
    with pytest.raises(Killed):
        forwarder.step()

    assert kit.forwarder().step() == 3

    assert len(kit.at_the_hub()) == 3
    assert kit.wire.bodies[0] == kit.wire.bodies[1]


def test_the_bytes_a_non_opted_instance_sends_hold_no_name_and_no_assignee(kit: Kit) -> None:
    for n in range(4):
        kit.move(f"T-{n}")

    kit.drain(kit.forwarder())

    assert kit.wire.bodies
    for body in kit.wire.bodies:
        assert ASSIGNEE.encode() not in body
        assert all("assignee" not in e["fields"] for e in json.loads(body)["events"])
    assert all("assignee" not in e.fields for e in kit.at_the_hub())


def test_an_opted_in_instance_sends_the_names_and_the_hub_keeps_them(kit: Kit) -> None:
    kit.move("T-1")
    forward.main(["opt-in", "--config", str(kit.config)])

    kit.drain(kit.forwarder())

    [stored] = kit.at_the_hub()
    assert stored.fields["assignee"] == ASSIGNEE


def test_an_opt_out_applies_while_the_hub_is_unreachable(kit: Kit) -> None:
    forward.main(["opt-in", "--config", str(kit.config)])
    kit.move("T-1")
    forwarder = kit.forwarder()
    kit.wire.down = True
    assert forwarder.step() is None  # named, and refused by the network

    reached = kit.wire.attempts
    assert forward.main(["opt-out", "--config", str(kit.config)]) == 0
    assert kit.wire.attempts == reached  # the opt-out needed no hub

    kit.wire.down = False
    kit.drain(forwarder)
    assert all(ASSIGNEE.encode() not in body for body in kit.wire.bodies)
    assert all("assignee" not in e.fields for e in kit.at_the_hub())


def test_an_opt_out_made_in_the_panel_stops_the_names_in_the_next_batch_with_the_hub_down(
    kit: Kit, tmp_path: Path
) -> None:
    kit.move("T-1")
    forwarder = kit.forwarder()
    (tmp_path / "ic").mkdir()

    def panel(server: Any, opt_in: bool) -> dict[str, Any]:
        request = urllib.request.Request(
            url(server, "/api/forwarding"),
            data=json.dumps({"opt_in": opt_in}).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request) as answer:
            return json.load(answer)

    with serve(tmp_path / "ic", forwarding=forwarder) as ic:
        listed = panel(ic, True)
        assert listed["names"] is True and listed["next"][0]["fields"]["assignee"] == ASSIGNEE
        kit.wire.down = True
        assert forwarder.step() is None  # named, and refused by the network

        reached = kit.wire.attempts
        listed = panel(ic, False)
        assert kit.wire.attempts == reached  # the toggle needed no hub
        assert listed["names"] is False and "assignee" not in listed["next"][0]["fields"]
        assert "unreachable" in listed["problem"]

    kit.wire.down = False
    kit.drain(forwarder)
    assert all(ASSIGNEE.encode() not in body for body in kit.wire.bodies)
    assert all("assignee" not in e.fields for e in kit.at_the_hub())


def test_a_wrong_or_revoked_token_answers_401_and_writes_nothing(kit: Kit) -> None:
    kit.move("T-1")
    forwarder = kit.forwarder(token="revoked")

    assert forwarder.step() is None

    assert kit.wire.statuses == [401]
    assert kit.at_the_hub() == []
    assert kit.cursor() is None


def test_a_hub_for_aggregates_only_refuses_an_opt_in_and_takes_the_batch_without_names(aggregates_kit: Kit) -> None:
    kit = aggregates_kit
    kit.move("T-1")
    forward.main(["opt-in", "--config", str(kit.config)])
    forwarder = kit.forwarder()

    assert forwarder.step() is None
    assert kit.wire.statuses == [403]
    assert kit.at_the_hub() == []

    assert forwarder.step() == 1
    assert kit.wire.statuses == [403, 200]
    [stored] = kit.at_the_hub()
    assert "assignee" not in stored.fields
