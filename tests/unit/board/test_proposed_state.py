"""A Proposed State is declared by role: admission never takes it, the kanban never draws it, it leaves only by
promotion or drop, and a trajectory starts at promotion."""

from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.view import board_columns
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.model.level import Level, Terminal
from starpulse.flow_metrics.model.level_metrics import Run
from starpulse.flow_metrics.model.trajectories import trajectory_analytics
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError
from starpulse.machine_engine.model.snapshot import describe
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.transitions import Table
from starpulse.scheduler.model.admission import decide
from starpulse.scheduler.model.config import DIMENSIONS, Scheduler
from starpulse.scheduler.model.ledger import Ledger
from starpulse.scheduler.model.sampler import Reading

MACHINES = Path(__file__).parent.parent.parent / "fixtures" / "machines"
PROPOSED_BOARD = MACHINES / "proposed-board.yaml"
POLICY = Scheduler(lane="ready")
H = 3600.0


def _feed() -> BoardFeed:
    compiled = load_machine(PROPOSED_BOARD)
    feed = BoardFeed(clock=lambda: 100.0, roles=StateRoles.of_machine(compiled))
    feed.expect("0-0")
    return feed


def _agents(feed: BoardFeed) -> list[dict]:
    return feed.snapshot()["flows"][0]["agents"]


def test_proposed_is_never_admitted(tmp_path: Path) -> None:
    feed = _feed()
    feed.put(BoardTask(id="PROJ-1", team="demo", title="proposed", lane="proposed"))
    feed.put(BoardTask(id="PROJ-2", team="demo", title="ready", lane="ready"))
    tasks = [
        {"id": a["id"], "state": a["state"], "workable": a["workable"], "model": "@agent-standard-high"}
        | {"labels": ["size-1"], "dependencies": []}
        for a in _agents(feed)
    ]
    readings = [Reading(name, 0, POLICY.limits[name]) for name in DIMENSIONS]
    ledger = Ledger(EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))

    decisions = decide(tasks, "ready", readings, POLICY, {}, ledger)

    assert [d.task for d in decisions] == ["PROJ-2"]
    assert {a["id"]: a["workable"] for a in _agents(feed)}["PROJ-1"] is False


def test_proposed_is_not_on_the_kanban() -> None:
    compiled = load_machine(PROPOSED_BOARD)
    roles = StateRoles.of_machine(compiled)
    feed = BoardFeed(clock=lambda: 100.0, roles=roles, machines={"board": describe(compiled.machine)})
    feed.expect("0-0")
    feed.put(BoardTask(id="PROJ-1", team="demo", title="proposed", lane="proposed"))

    columns = board_columns(feed.snapshot(), lambda agent: True)["columns"]

    assert "proposed" not in [column["state"] for column in columns]
    assert "ready" in [column["state"] for column in columns]
    assert roles.proposed == "proposed"
    assert roles.wire()["proposed"] == "proposed"


def test_proposed_exits_only_promote_or_drop() -> None:
    table = Table(describe(load_machine(PROPOSED_BOARD).machine))
    here = frozenset({"proposed"})

    assert table.place(here, "PROMOTE", lenient=False) == {"ready"}
    assert table.place(here, "DROP", lenient=False) == {"archived"}
    assert table.place(here, "START", lenient=False) == frozenset()
    assert table.place(here, "ARCHIVE", lenient=False) == frozenset()


def test_proposed_exits_only_promote_or_drop_is_enforced_when_a_machine_compiles(tmp_path: Path) -> None:
    leaky = PROPOSED_BOARD.read_text().replace(
        "  DROP: [{from: proposed, to: archived}]",
        "  DROP: [{from: proposed, to: archived}]\n  SKIP: [{from: proposed, to: in_progress}]",
    )
    path = tmp_path / "leaky.yaml"
    path.write_text(leaky)

    with pytest.raises(MachineDefinitionError, match="proposed"):
        load_machine(path)


def test_trajectory_starts_at_promotion() -> None:
    machine = {
        "states": [
            {"id": "proposed", "initial": False, "final": False, "role": "proposed"},
            {"id": "todo", "initial": True, "final": False},
            {"id": "work", "initial": False, "final": False},
            {"id": "done", "initial": False, "final": True},
        ]
    }
    level = Level("board", "done", (Terminal("done", "goal"),))
    control = Run("a", "T-0", ((0.0, "todo"), (5 * H, "work"), (10 * H, "done")))
    proposed = Run("a", "T-1", ((0.0, "proposed"), (50 * H, "todo"), (60 * H, "work"), (70 * H, "done")))

    result = trajectory_analytics(level, machine, [control, proposed], now=100 * H, window_s=100 * H)

    assert result["variants"] == [{"path": ["todo", "work", "done"], "count": 2, "share": 1.0}]
