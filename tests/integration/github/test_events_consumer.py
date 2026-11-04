"""The `events` consumer: a saved delivery becomes one typed `github-pull-request` machine event through the ingest."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select

from starpulse.event_log.event_log import EventLog, Tail
from starpulse.event_log.migrate import migrate_chain
from starpulse.github.adapters.inbound.consumer import consume
from starpulse.github.adapters.outbound.ingest import HttpIngest
from starpulse.github.adapters.outbound.inbox import SqlInbox
from starpulse.github.adapters.outbound.queue import SqlQueue, github_inbox_state
from starpulse.github.adapters.outbound.verdicts import Verdicts
from starpulse.github.model.delivery import Delivery
from starpulse.github.model.events import BUDGET, backoff
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.snapshot import describe
from starpulse.machine_engine.model.transitions import board_machine
from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest
from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
from starpulse.runs.model.config import Producer
from starpulse.runtime.adapter_kit import serve, url

from tests.machine_feed import MachineFeed

MACHINE = Path(__file__).parents[3] / "starpulse" / "machines" / "github-pull-request.yaml"
EVENTS = ("PR_OPENED", "PR_MERGED", "PR_CLOSED", "PR_REOPENED", "CHECKS_PASSED", "CHECKS_FAILED")
REPO = "acme/widgets"
HEAD = "a" * 40
MERGE = "b" * 40
PRODUCER = Producer("github", "GITHUB_TOKEN", machines=("github-pull-request",), actors=("github",))
TOKEN = "github-secret"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class Linked:
    """The task each pull request is linked to; a pull request not named is unlinked."""

    def __init__(self, tasks: dict[int, str]) -> None:
        self.tasks = tasks

    def task_for(self, repository: str, number: int) -> str | None:
        return self.tasks.get(number) if repository == REPO else None


@dataclass
class Answers:
    """An ingest that answers every post with `status` and keeps what it was sent."""

    status: int
    posted: int = 0

    def post(self, event: dict) -> int:
        self.posted += 1
        return self.status


@dataclass
class World:
    inbox: SqlInbox
    queue: SqlQueue
    clock: Clock
    log: EventLog
    ingest: HttpIngest
    links: Linked
    n: int = 0

    def save(self, event: str, payload: dict, delivery_id: str | None = None) -> str:
        self.n += 1
        delivery_id = delivery_id or f"d-{self.n}"
        action = payload.get("action", "")
        self.inbox.save(Delivery(delivery_id, event, action, REPO, json.dumps(payload).encode()))
        return delivery_id

    def run(self, ingest: object | None = None) -> None:
        consume(self.queue, ingest or self.ingest, self.links)

    def events(self) -> list[dict]:
        return [entry.fields for entry in Tail.replay(self.log, "machine:events").poll()]

    def state(self, delivery_id: str) -> dict:
        with self.inbox.engine.connect() as db:
            row = db.execute(
                select(github_inbox_state).where(github_inbox_state.c.delivery_id == delivery_id)
            ).mappings().one()
        return dict(row)


def pull_request(action: str, *, number: int = 7, merged: bool = False, bot: bool = False) -> dict:
    return {
        "action": action,
        "number": number,
        "repository": {"full_name": REPO},
        "pull_request": {
            "number": number,
            "merged": merged,
            "merge_commit_sha": MERGE if merged else None,
            "head": {"sha": HEAD},
            "user": {"type": "Bot" if bot else "User"},
        },
    }


def check_suite(conclusion: str, *, number: int = 7, suite: int = 555, head: str = HEAD) -> dict:
    return {
        "action": "completed",
        "repository": {"full_name": REPO},
        "check_suite": {"id": suite, "head_sha": head, "conclusion": conclusion, "pull_requests": [{"number": number}]},
    }


def check_run(conclusion: str, *, number: int = 7, suite: int = 555) -> dict:
    return {
        "action": "completed",
        "repository": {"full_name": REPO},
        "check_run": {
            "head_sha": HEAD,
            "conclusion": conclusion,
            "check_suite": {"id": suite},
            "pull_requests": [{"number": number}],
        },
    }


@pytest.fixture
def machines(tmp_path: Path) -> dict:
    drawn = describe(load_machine(MACHINE).machine)
    return {"board": board_machine(("To Do", "Done")), "github-pull-request": drawn}


@pytest.fixture
def world(tmp_path: Path, machines: dict) -> Iterator[World]:
    feed = MachineFeed(tmp_path / "events.sqlite", machines)
    events = CloudEventsIngest(
        {PRODUCER.name: PRODUCER}, ingest_tokens([PRODUCER], {"GITHUB_TOKEN": TOKEN}), feed.log, feed.feed.machines
    )
    clock = Clock()
    inbox = SqlInbox(f"sqlite:///{tmp_path / 'inbox.sqlite'}", migrate_chain, clock)
    with serve(tmp_path, feed.feed, events=events) as server:
        yield World(
            inbox,
            SqlQueue(inbox.engine, "events", clock),
            clock,
            feed.log,
            HttpIngest(url(server, ""), TOKEN),
            Linked({7: "TASK-7"}),
        )
    inbox.engine.dispose()


def test_a_merged_delivery_yields_one_event_for_the_linked_task_and_its_redelivery_none(world: World) -> None:
    first = world.save("pull_request", pull_request("closed", merged=True))
    world.run()
    again = world.save("pull_request", pull_request("closed", merged=True))
    world.run()

    [event] = world.events()
    assert (event["event"], event["machine"], event["task"], event["actor"], event["source"]) == (
        "PR_MERGED", "github-pull-request", "TASK-7", "github", "github",
    )  # fmt: skip
    assert world.state(first)["status"] == world.state(again)["status"] == "done"


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [
        ("pull_request", pull_request("opened"), "PR_OPENED"),
        ("pull_request", pull_request("reopened"), "PR_REOPENED"),
        ("pull_request", pull_request("closed"), "PR_CLOSED"),
        ("pull_request", pull_request("closed", merged=True), "PR_MERGED"),
        ("check_suite", check_suite("success"), "CHECKS_PASSED"),
        ("check_suite", check_suite("failure"), "CHECKS_FAILED"),
        ("check_run", check_run("failure"), "CHECKS_FAILED"),
    ],
)
def test_each_delivery_maps_to_its_event_with_an_id_derived_from_the_fact(
    world: World, event: str, payload: dict, expected: str
) -> None:
    world.save(event, payload)
    world.save(event, payload)  # a second delivery of the one fact
    world.run()

    [recorded] = world.events()
    assert recorded["event"] == expected
    assert recorded["event_id"].startswith("github/")


def test_a_new_sha_or_suite_is_a_new_fact_with_its_own_event_id(world: World) -> None:
    world.save("check_suite", check_suite("failure", suite=1))
    world.save("check_suite", check_suite("failure", suite=2))
    world.save("check_suite", check_suite("failure", suite=2, head="c" * 40))
    world.run()

    assert len({event["event_id"] for event in world.events()}) == 2


def test_deliveries_that_carry_no_pull_request_fact_are_skipped(world: World) -> None:
    passing_run = world.save("check_run", check_run("success"))
    stray = world.save("check_suite", check_suite("success", number=7) | {"action": "requested"})
    world.run()

    assert world.events() == []
    assert world.state(passing_run)["status"] == world.state(stray)["status"] == "skipped"


def test_an_ingest_outage_backs_off_then_delivers_once_when_the_ingest_returns(world: World) -> None:
    with socket.socket() as spare:
        spare.bind(("127.0.0.1", 0))
        down = HttpIngest(f"http://127.0.0.1:{spare.getsockname()[1]}", TOKEN)
    delivery = world.save("pull_request", pull_request("opened"))
    start = world.clock.now

    world.run(down)
    assert (world.state(delivery)["status"], world.state(delivery)["attempts"]) == ("pending", 1)
    assert world.state(delivery)["next_attempt_at"] == start + 2
    world.run(down)  # not due yet: nothing is tried
    assert world.state(delivery)["attempts"] == 1

    world.clock.now = start + 2
    world.run(down)
    assert world.state(delivery)["next_attempt_at"] == start + 2 + 4
    assert world.events() == []

    world.clock.now = start + 6
    world.run()
    assert [event["event"] for event in world.events()] == ["PR_OPENED"]
    assert world.state(delivery)["status"] == "done"


@pytest.mark.parametrize("status", [400, 403, 413])
def test_an_ingest_refusal_dead_letters_at_once(world: World, status: int) -> None:
    delivery = world.save("pull_request", pull_request("opened"))
    refusing = Answers(status)

    world.run(refusing)

    assert (world.state(delivery)["status"], world.state(delivery)["attempts"]) == ("dead", 1)
    assert str(status) in world.state(delivery)["last_error"]
    world.clock.now += 10_000
    world.run(refusing)
    assert refusing.posted == 1


def test_the_tenth_failure_dead_letters_and_the_wait_is_capped(world: World) -> None:
    delivery = world.save("pull_request", pull_request("opened"))
    failing = Answers(503)
    waits = []

    for _ in range(BUDGET):
        before = world.clock.now
        world.run(failing)
        waits.append(world.state(delivery)["next_attempt_at"] - before)
        world.clock.now += 1_000

    assert failing.posted == BUDGET
    assert world.state(delivery)["status"] == "dead"
    assert waits[:9] == [min(2**n, 300) for n in range(1, 10)]
    assert backoff(9) == 300


def test_an_unlinked_pull_request_is_retried_then_skipped_as_no_task(world: World) -> None:
    delivery = world.save("pull_request", pull_request("opened", number=99))
    bot = world.save("pull_request", pull_request("opened", number=98, bot=True))
    refusing = Answers(201)

    world.run(refusing)
    assert world.state(delivery)["status"] == "pending"
    assert world.state(bot)["status"] == "skipped"

    for _ in range(BUDGET):
        world.clock.now += 1_000
        world.run(refusing)

    assert (world.state(delivery)["status"], world.state(delivery)["last_error"]) == ("skipped", "no-task")
    assert refusing.posted == 0
    assert world.events() == []


def test_the_dead_row_gauge_counts_a_dead_row_until_it_is_requeued(world: World) -> None:
    delivery = world.save("pull_request", pull_request("opened"))
    world.run(Answers(400))
    gauge = Verdicts(world.queue.dead_counts)
    line = 'starpulse_github_dead_rows{consumer="events"}'

    assert f"{line} 1.0" in gauge.exposition().decode()
    assert world.queue.requeue(delivery) is True
    assert f"{line} 0.0" in gauge.exposition().decode()
    assert (world.state(delivery)["status"], world.state(delivery)["attempts"]) == ("pending", 0)

    world.run()
    assert [event["event"] for event in world.events()] == ["PR_OPENED"]


def test_a_dismissed_dead_row_is_skipped_and_only_a_dead_row_can_be_requeued_or_dismissed(world: World) -> None:
    delivery = world.save("pull_request", pull_request("opened"))
    live = world.save("pull_request", pull_request("closed"))
    world.run(Answers(400))
    world.clock.now += 1
    world.queue.requeue(live)

    assert world.queue.dismiss(delivery) is True
    assert world.queue.dismiss(delivery) is False
    assert world.queue.requeue("no-such-delivery") is False
    assert world.state(delivery)["status"] == "skipped"
    assert world.queue.dead_counts() == {"events": 0}


def test_done_and_skipped_rows_are_purged_after_seven_days_and_pending_ones_kept(world: World) -> None:
    done = world.save("pull_request", pull_request("opened"))
    skipped = world.save("pull_request", pull_request("opened", bot=True))
    world.run()
    pending = world.save("pull_request", pull_request("closed"))
    world.run(Answers(503))

    world.clock.now += 7 * 86400 + 1
    world.queue.purge()

    with world.inbox.engine.connect() as db:
        kept = {row.delivery_id for row in db.execute(select(github_inbox_state))}
    assert kept == {pending}
    assert {done, skipped}.isdisjoint(kept)


def test_the_github_actor_writes_each_of_the_six_events(machines: dict) -> None:
    writers = machines["github-pull-request"]["writers"]

    assert all("github" in [w["actor"] for w in writers[event]] for event in EVENTS)
