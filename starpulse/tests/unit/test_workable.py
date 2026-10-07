"""Whether each open task can be worked yet, and since when, on the Board snapshot."""

from pathlib import Path
from typing import Any

import pytest

from starpulse import criteria
from starpulse.board_feed import BoardFeed
from starpulse.contracts.adapters import BoardTask
from starpulse.store.history import HistoryStore

BLOCK = """## Start Criteria

```yaml
start_criteria:
- id: soak
  kind: prom
  expr: time()
  at_least: 1
- id: rows
  kind: sql
  query: select 1
  equals: 1
```
"""


def _task(task_id: str, lane: str = "ready", **fields: Any) -> BoardTask:
    return BoardTask(id=task_id, team="demo", title=task_id, lane=lane, **fields)


def _agent(feed: BoardFeed, task_id: str) -> dict:
    return next(a for a in feed.snapshot()["flows"][0]["agents"] if a["id"] == task_id)


def _live(clock: list[float]) -> BoardFeed:
    feed = BoardFeed(clock=lambda: clock[0])
    feed.expect("0-0")  # read up to the stream's end: every put from here is live
    return feed


def _drain(deltas: Any) -> list[tuple[str, dict]]:
    drained = []
    while not deltas.empty():
        drained.append(deltas.get_nowait())
    return drained


class Evaluator:
    """Answers each criterion with `status` and counts the calls."""

    def __init__(self, status: str = "met") -> None:
        self.status = status
        self.calls = 0

    def __call__(self, task: str, description: str) -> list[dict]:
        self.calls += 1
        return [{**c, "status": self.status} for c in criteria.authored(description)]


def test_a_task_with_no_dependency_and_no_gate_is_workable_since_it_entered_its_lane() -> None:
    now = [100.0]
    feed = _live(now)

    feed.put(_task("PROJ-1"))

    agent = _agent(feed, "PROJ-1")
    assert (agent["workable"], agent["workable_since"]) == (True, 100.0)


def test_a_task_waits_on_a_dependency_until_it_is_done_and_is_workable_since_the_latest_of_its_entry_and_completion() -> (
    None
):
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", "in_progress"))
    feed.put(_task("PROJ-2", "ready", dependencies=("PROJ-1",)))
    assert (_agent(feed, "PROJ-2")["workable"], _agent(feed, "PROJ-2")["workable_since"]) == (False, None)

    now[0] = 300.0
    feed.put(_task("PROJ-1", settled="completed", settled_at=250.0))

    agent = _agent(feed, "PROJ-2")
    assert (agent["workable"], agent["workable_since"]) == (True, 250.0)


def test_a_dependency_completed_before_the_task_entered_its_lane_leaves_the_entry_time() -> None:
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", settled="completed", settled_at=40.0))
    now[0] = 120.0

    feed.put(_task("PROJ-2", dependencies=("PROJ-1",)))

    assert _agent(feed, "PROJ-2")["workable_since"] == 120.0


def test_a_dependency_in_the_done_lane_counts_from_when_it_entered_that_lane() -> None:
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-2", dependencies=("PROJ-1",)))
    feed.put(_task("PROJ-1", "in_progress"))
    now[0] = 400.0

    feed.put(_task("PROJ-1", "done"))

    agent = _agent(feed, "PROJ-2")
    assert (agent["workable"], agent["workable_since"]) == (True, 400.0)


@pytest.mark.parametrize("settled", ["archived", None])
def test_an_archived_or_unknown_dependency_is_not_done(settled: str | None) -> None:
    feed = _live([100.0])
    if settled:
        feed.put(_task("PROJ-1", settled=settled, settled_at=50.0))

    feed.put(_task("PROJ-2", dependencies=("PROJ-1",)))

    assert _agent(feed, "PROJ-2")["workable"] is False


def test_a_dependent_is_republished_when_its_dependency_completes() -> None:
    feed = _live([100.0])
    feed.put(_task("PROJ-1", "in_progress"))
    feed.put(_task("PROJ-2", dependencies=("PROJ-1",)))
    _, deltas = feed.subscribe()

    feed.put(_task("PROJ-1", settled="completed", settled_at=150.0))

    seen = {}
    while not deltas.empty():
        kind, data = deltas.get_nowait()
        seen[data["id"]] = data["agent"]
    assert seen["PROJ-2"]["workable"] is True
    assert seen["PROJ-1"] is None


def test_a_waiting_task_with_neither_criteria_nor_dependencies_is_workable() -> None:
    feed = _live([100.0])

    feed.put(_task("PROJ-1", "waiting"))

    assert _agent(feed, "PROJ-1")["workable"] is True


@pytest.mark.parametrize("status", ["unmet", "not evaluated", "error"])
def test_a_waiting_task_is_not_workable_while_its_criteria_are_unmet_not_evaluated_or_in_error(status: str) -> None:
    feed = _live([100.0])
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    feed.track_criteria(Evaluator(status), None)

    feed.evaluate_criteria()

    agent = _agent(feed, "PROJ-1")
    assert (agent["workable"], agent["workable_since"]) == (False, None)


def test_a_task_with_criteria_and_no_evaluator_is_never_workable() -> None:
    feed = _live([100.0])
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    feed.track_criteria(None, None)

    feed.evaluate_criteria()

    assert _agent(feed, "PROJ-1")["workable"] is False


def test_a_waiting_task_is_workable_since_the_first_pass_that_saw_every_criterion_met() -> None:
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    evaluator = Evaluator()
    feed.track_criteria(evaluator, None)
    _, deltas = feed.subscribe()

    now[0] = 500.0
    feed.evaluate_criteria()
    now[0] = 600.0
    feed.evaluate_criteria()

    agent = _agent(feed, "PROJ-1")
    assert (agent["workable"], agent["workable_since"]) == (True, 500.0)
    assert [d[1]["agent"]["workable"] for d in _drain(deltas)] == [True]


def test_a_task_whose_criteria_fall_unmet_again_starts_a_new_wait() -> None:
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    evaluator = Evaluator()
    feed.track_criteria(evaluator, None)
    now[0] = 500.0
    feed.evaluate_criteria()

    evaluator.status = "unmet"
    now[0] = 600.0
    feed.evaluate_criteria()
    assert _agent(feed, "PROJ-1")["workable"] is False

    evaluator.status = "met"
    now[0] = 700.0
    feed.evaluate_criteria()
    assert _agent(feed, "PROJ-1")["workable_since"] == 700.0


def test_a_waiting_task_is_not_evaluated_while_a_dependency_is_not_done_and_counts_from_its_completion() -> None:
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", "in_progress"))
    feed.put(_task("PROJ-2", "waiting", description=BLOCK, dependencies=("PROJ-1",)))
    evaluator = Evaluator()
    feed.track_criteria(evaluator, None)

    now[0] = 200.0
    feed.evaluate_criteria()
    assert evaluator.calls == 0

    now[0] = 300.0
    feed.put(_task("PROJ-1", settled="completed", settled_at=250.0))
    now[0] = 400.0
    feed.evaluate_criteria()

    agent = _agent(feed, "PROJ-2")
    assert (agent["workable"], agent["workable_since"]) == (True, 400.0)


def test_a_snapshot_and_a_subscription_never_run_the_evaluator() -> None:
    feed = _live([100.0])
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    evaluator = Evaluator()
    feed.track_criteria(evaluator, None)

    feed.snapshot()
    feed.subscribe()
    feed.subscribe()

    assert evaluator.calls == 0


def test_the_moment_the_criteria_were_met_survives_a_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    now = [100.0]
    first = _live(now)
    first.put(_task("PROJ-1", "waiting", description=BLOCK))
    first.track_criteria(Evaluator(), HistoryStore(url, {}))
    now[0] = 500.0
    first.evaluate_criteria()

    now[0] = 900.0
    restarted = BoardFeed(clock=lambda: now[0])  # replaying: the lane entry is dated by the history
    restarted.date_lanes(lambda _task: [{"at": 100.0, "from": None, "to": "Waiting"}])
    restarted.put(_task("PROJ-1", "waiting", description=BLOCK))
    restarted.track_criteria(Evaluator(), HistoryStore(url, {}))
    restarted.evaluate_criteria()

    assert _agent(restarted, "PROJ-1")["workable_since"] == 500.0


def test_a_met_moment_for_criteria_that_fell_unmet_is_forgotten_by_the_store(tmp_path: Path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", {})
    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    evaluator = Evaluator()
    feed.track_criteria(evaluator, store)
    now[0] = 500.0
    feed.evaluate_criteria()
    assert store.criteria_met() == {"PROJ-1": 500.0}

    evaluator.status = "unmet"
    feed.evaluate_criteria()

    assert store.criteria_met() == {}


def test_a_store_that_cannot_be_written_leaves_the_pass_in_memory() -> None:
    class Down:
        def criteria_met(self) -> dict[str, float]:
            return {}

        def save_criteria_met(self, met: dict[str, float]) -> None:
            raise RuntimeError("down")

    now = [100.0]
    feed = _live(now)
    feed.put(_task("PROJ-1", "waiting", description=BLOCK))
    feed.track_criteria(Evaluator(), Down())
    now[0] = 500.0

    feed.evaluate_criteria()

    assert _agent(feed, "PROJ-1")["workable_since"] == 500.0
