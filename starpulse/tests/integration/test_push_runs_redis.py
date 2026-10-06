"""The runs stream against a real Redis: pushed runs reach the page snapshot, and their learned graph outlives a restart."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import redis as redis_lib

from starpulse import run_events
from starpulse.board_feed import BoardFeed
from starpulse.history import HistoryStore
from starpulse.push_runs import PUSHED_INSTANCE, PushRuns, build_consumer
from starpulse.streams import StreamConsumer, StreamProducer

GROUP = "flow-view-test"


class Pushed:
    """One view reading the runs stream: `emit` writes it, `read` takes what it holds into the feed."""

    def __init__(self, redis_client: redis_lib.Redis, monkeypatch: pytest.MonkeyPatch, history: HistoryStore) -> None:
        monkeypatch.setattr(StreamConsumer, "connect", lambda self: redis_client)
        redis_client.xgroup_create(run_events.STREAM, GROUP, id="0", mkstream=True)
        self.feed = BoardFeed()
        self.consumer = build_consumer(PushRuns(self.feed.runs(PUSHED_INSTANCE), history), GROUP)
        self.consumer.read_block_ms = 100
        self.producer = StreamProducer(stream=run_events.STREAM, client_factory=lambda: redis_client)
        self.client = redis_client

    def emit(self, phase: str, *flags: str) -> None:
        """Write what `starpulse emit <phase> <flags>` builds onto the Redis stream this reader still consumes."""
        given = dict(zip(flags[::2], flags[1::2], strict=True))
        entry = run_events.entry(
            phase,
            given["--workflow"],
            given["--run"],
            given["--status"],
            now=time.time(),
            step=given.get("--step"),
            depends=given["--depends"].split(",") if "--depends" in given else None,
        )
        assert self.producer.emit(entry) is not None

    def read(self) -> dict:
        self.consumer.consume_once(self.client)
        return next(dag for dag in self.feed.snapshot()["dags"] if dag["name"] == "pushed/nightly")


@pytest.fixture
def view(redis_client: redis_lib.Redis, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Pushed:
    return Pushed(redis_client, monkeypatch, HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", {}))


def test_emit_start_and_end_show_the_run_with_its_status_on_the_page(view: Pushed) -> None:
    view.emit("start", "--workflow", "nightly", "--run", "r1", "--status", "running")
    assert view.read()["status"] == "running"

    view.emit("end", "--workflow", "nightly", "--run", "r1", "--status", "failed")
    dag = view.read()

    assert (dag["status"], dag["runId"]) == ("failed", "r1")
    assert dag["finishedAt"] != ""


def test_steps_emitted_with_depends_draw_their_edges_and_survive_a_restart(
    view: Pushed, redis_client: redis_lib.Redis, tmp_path: Path
) -> None:
    view.emit("start", "--workflow", "nightly", "--run", "r1", "--status", "running")
    view.emit("end", "--workflow", "nightly", "--run", "r1", "--status", "succeeded", "--step", "fetch")
    view.emit(
        "start", "--workflow", "nightly", "--run", "r1", "--status", "running",
        "--step", "load", "--depends", "fetch",
    )  # fmt: skip
    dag = view.read()
    assert {step["name"]: step["depends"] for step in dag["steps"]} == {"fetch": [], "load": ["fetch"]}

    redis_client.xtrim(run_events.STREAM, maxlen=0)  # the stream no longer holds the steps: only the history does
    restarted = BoardFeed()
    PushRuns(restarted.runs(PUSHED_INSTANCE), HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", {}))

    (dag,) = restarted.snapshot()["dags"]
    assert {step["name"]: step["depends"] for step in dag["steps"]} == {"fetch": [], "load": ["fetch"]}
