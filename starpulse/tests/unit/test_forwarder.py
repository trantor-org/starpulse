"""The IC's forwarder: batches from a persisted cursor that moves only when the hub acknowledges."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from starpulse import events, run_events
from starpulse.config import Forward
from starpulse.event_log import EventLog
from starpulse.forward import Forwarder, OptIn
from starpulse.history import HistoryStore

URL = "https://hub.example.test"


class FakeHub:
    """Stands where the network is: records each POST and answers from `answers`, then 200."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, dict]] = []
        self.answers: list[int | OSError] = []

    def __call__(self, url: str, token: str, body: bytes) -> tuple[int, dict]:
        self.posts.append((url, token, json.loads(body)))
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, OSError):
            raise answer
        return answer, {}

    def event_ids(self) -> list[list[str]]:
        return [[e["event_id"] for e in body["events"]] for _, _, body in self.posts]


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.url = f"sqlite:///{tmp_path / 'ic.sqlite'}"
        self.log = EventLog(self.url)
        self.store = HistoryStore(self.url, {})
        self.opt_in = OptIn(tmp_path / "starpulse-forward.json")
        self.hub = FakeHub()

    def forwarder(self, *, batch: int = 50, url: str = URL) -> Forwarder:
        return Forwarder(self.log, self.store, Forward(url, "HUB_TOKEN", batch), "secret", self.opt_in, send=self.hub)

    def move(self, task: str, actor: str = "ana") -> None:
        events.publish("board", "MOVED", actor=actor, task=task, now=1.0, log=self.log)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_a_step_posts_the_log_in_order_under_the_token_and_saves_the_cursor_after_the_hub_answers(rig: Rig) -> None:
    for task in ("T-1", "T-2"):
        rig.move(task)

    sent = rig.forwarder().step()

    assert sent == 2
    [(url, token, body)] = rig.hub.posts
    assert (url, token) == (f"{URL}/api/forward", "secret")
    assert [e["fields"]["task"] for e in body["events"]] == ["T-1", "T-2"]
    assert rig.store.cursor(f"forward:{URL}") == 2


def test_a_step_with_nothing_new_posts_nothing(rig: Rig) -> None:
    forwarder = rig.forwarder()
    assert forwarder.step() == 0
    rig.move("T-1")
    forwarder.step()

    assert forwarder.step() == 0
    assert len(rig.hub.posts) == 1


def test_a_batch_holds_at_most_the_configured_number_of_events(rig: Rig) -> None:
    for n in range(7):
        rig.move(f"T-{n}")
    forwarder = rig.forwarder(batch=3)

    assert [forwarder.step() for _ in range(3)] == [3, 3, 1]
    assert [len(ids) for ids in rig.hub.event_ids()] == [3, 3, 1]
    assert len({i for ids in rig.hub.event_ids() for i in ids}) == 7


@pytest.mark.parametrize("answer", [401, 403, 500, 503, OSError("hub unreachable")])
def test_a_batch_the_hub_did_not_acknowledge_is_sent_again_whole(rig: Rig, answer: int | OSError) -> None:
    rig.move("T-1")
    rig.move("T-2")
    rig.hub.answers = [answer]
    forwarder = rig.forwarder()

    assert forwarder.step() is None
    assert rig.store.cursor(f"forward:{URL}") is None
    assert forwarder.step() == 2

    assert rig.hub.event_ids()[0] == rig.hub.event_ids()[1]
    assert rig.store.cursor(f"forward:{URL}") == 2


def test_a_forwarder_started_again_resumes_after_the_cursor_the_last_one_saved(rig: Rig) -> None:
    rig.move("T-1")
    rig.forwarder().step()
    rig.move("T-2")

    assert rig.forwarder().step() == 1

    assert [[e["fields"]["task"] for e in body["events"]] for _, _, body in rig.hub.posts] == [["T-1"], ["T-2"]]


def test_a_new_hub_address_replays_the_retained_log_to_the_new_hub(rig: Rig) -> None:
    rig.move("T-1")
    rig.forwarder().step()

    assert rig.forwarder(url="https://other.example.test").step() == 1


def test_only_the_machine_and_runs_streams_are_forwarded_and_the_cursor_passes_the_rest(rig: Rig) -> None:
    rig.log.append("claude:session", {"secret": "x"})
    rig.move("T-1")
    rig.log.append(
        run_events.STREAM,
        run_events.entry("end", "nightly", "r1", "succeeded", now=2.0),
    )
    rig.log.append("claude:session", {"secret": "y"})

    assert rig.forwarder().step() == 2

    [(_, _, body)] = rig.hub.posts
    assert [e["stream"] for e in body["events"]] == [events.STREAM, run_events.STREAM]
    assert rig.store.cursor(f"forward:{URL}") == 4


def test_a_log_holding_only_other_streams_moves_the_cursor_without_a_post(rig: Rig) -> None:
    rig.log.append("claude:session", {"secret": "x"})

    assert rig.forwarder().step() == 0

    assert rig.hub.posts == []
    assert rig.store.cursor(f"forward:{URL}") == 1


def test_a_named_event_leaves_without_its_name_until_the_instance_opts_in(rig: Rig) -> None:
    rig.move("T-1", actor="ana")
    forwarder = rig.forwarder()
    forwarder.step()
    rig.opt_in.set(True)
    rig.move("T-2", actor="ana")
    forwarder.step()

    first, second = (body["events"][0]["fields"] for _, _, body in rig.hub.posts)
    assert "actor" not in first
    assert second["actor"] == "ana"
    assert [body["opt_in"] for _, _, body in rig.hub.posts] == [False, True]


def test_a_batch_that_failed_while_opted_in_is_sent_without_names_once_the_instance_opts_out(rig: Rig) -> None:
    rig.opt_in.set(True)
    rig.move("T-1", actor="ana")
    rig.hub.answers = [OSError("hub unreachable")]
    forwarder = rig.forwarder()
    forwarder.step()

    rig.opt_in.set(False)
    forwarder.step()

    named, anonymous = (body for _, _, body in rig.hub.posts)
    assert named["events"][0]["fields"]["actor"] == "ana"
    assert anonymous["opt_in"] is False
    assert "actor" not in anonymous["events"][0]["fields"]


def test_a_hub_that_refuses_the_opt_in_gets_the_batch_without_names_and_asked_again_after_an_opt_out(rig: Rig) -> None:
    rig.opt_in.set(True)
    rig.move("T-1", actor="ana")
    rig.hub.answers = [403]
    forwarder = rig.forwarder()
    assert forwarder.step() is None

    assert forwarder.step() == 1
    rig.opt_in.set(False)
    forwarder.step()
    rig.opt_in.set(True)
    rig.move("T-2", actor="ana")
    forwarder.step()

    assert [body["opt_in"] for _, _, body in rig.hub.posts] == [True, False, True]


def test_run_forwards_until_stopped(rig: Rig) -> None:
    rig.move("T-1")
    stop = threading.Event()
    forwarder = rig.forwarder()
    real = rig.hub.__call__

    def stop_after_the_post(url: str, token: str, body: bytes) -> tuple[int, dict]:
        try:
            return real(url, token, body)
        finally:
            stop.set()

    forwarder = Forwarder(
        rig.log, rig.store, Forward(URL, "HUB_TOKEN", 50), "secret", rig.opt_in, send=stop_after_the_post, interval=0.01
    )
    forwarder.run(stop)

    assert rig.hub.event_ids() == [[rig.hub.posts[0][2]["events"][0]["event_id"]]]
    assert rig.store.cursor(f"forward:{URL}") == 1


def test_run_goes_on_after_a_step_that_raises(rig: Rig) -> None:
    rig.move("T-1")
    stop = threading.Event()
    calls: list[int] = []

    def flaky(url: str, token: str, body: bytes) -> tuple[int, dict]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("not a network error")
        stop.set()
        return 200, {}

    Forwarder(rig.log, rig.store, Forward(URL, "HUB_TOKEN", 50), "secret", rig.opt_in, send=flaky, interval=0.01).run(
        stop
    )

    assert len(calls) == 2
