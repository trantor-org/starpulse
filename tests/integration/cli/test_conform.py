"""`starpulse conform`: the recorded history replayed against the machines the project declares."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime import conform

from tests.machines import MACHINES

BOARD = """\
name: Board
states:
  to_do: {initial: true}
  in_progress: {}
  done: {final: true}
events:
  CLAIM:
    - {from: to_do, to: in_progress}
  FINISH:
    - {from: in_progress, to: done}
"""
FLOW = """\
name: Review
states:
  open: {initial: true}
  merged: {}
  closed: {final: true}
events:
  MERGE:
    - {from: open, to: merged}
  CLOSE:
    - {from: merged, to: closed}
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project whose Board and `review` machines are declared in files, with a history that breaks both."""
    machines = tmp_path / ".starpulse" / "machines"
    machines.mkdir(parents=True)
    (machines / "board.yaml").write_text(BOARD)
    (machines / "review.yaml").write_text(FLOW)
    (tmp_path / ".starpulse" / "board" / "tasks").mkdir(parents=True)
    (tmp_path / ".starpulse" / "board" / "config.yml").write_text("project_name: Demo\n")
    (tmp_path / "starpulse.toml").write_text(
        f'database_url = "sqlite:///{tmp_path / "history.sqlite"}"\n'
        '[board]\ntype = "native"\npath = ".starpulse/board"\nmachine = ".starpulse/machines/board.yaml"\n'
    )
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for event_id, task, lane, at in (
        ("a", "T-1", "To Do", 1.0),
        ("b", "T-1", "In Progress", 2.0),
        ("c", "T-1", "Done", 3.0),
        ("d", "T-2", "To Do", 4.0),
        ("e", "T-2", "Done", 5.0),
    ):
        store.record_lane(event_id, task, lane, at)
    store.record_machine("m1", {"machine": "review", "event": "MERGE", "task": "T-1", "time": 6.0})
    store.record_machine("m2", {"machine": "review", "event": "MERGE", "task": "T-1", "time": 7.0})
    return tmp_path


def _run(project: Path, capsys: pytest.CaptureFixture[str], *flags: str) -> tuple[int, dict]:
    code = conform.main(["--config", str(project / "starpulse.toml"), *flags])
    return code, json.loads(capsys.readouterr().out)


def test_each_machine_is_replayed_with_its_event_count_and_every_violation(project, capsys) -> None:
    code, out = _run(project, capsys)

    by_machine = {m["machine"]: m for m in out["machines"]}
    assert code == 1
    assert (by_machine["board"]["replayed"], by_machine["board"]["violations"]) == (
        3,
        [{"source": "to_do", "move": "done", "count": 1, "tasks": ["T-2"]}],
    )
    assert (by_machine["review"]["replayed"], by_machine["review"]["violations"]) == (
        2,
        [{"source": "merged", "move": "MERGE", "count": 1, "tasks": ["T-1"]}],
    )
    assert (out["replayed"], out["violations"]) == (5, 2)


def test_a_history_the_machines_allow_exits_0(project, capsys) -> None:
    code, out = _run(project, capsys, "--since", "7", "--machine", "review")

    assert (code, out["violations"], [(m["machine"], m["replayed"]) for m in out["machines"]]) == (
        0,
        0,
        [("review", 1)],
    )


def test_a_machine_the_project_does_not_declare_exits_2(project, capsys) -> None:
    with pytest.raises(SystemExit) as refused:
        conform.main(["--config", str(project / "starpulse.toml"), "--machine", "nope"])

    assert refused.value.code == 2
