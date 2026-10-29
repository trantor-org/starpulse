"""Archiving a task others depend on: the native board's `archive` removes it from each open dependent's dependencies."""

from pathlib import Path

import yaml
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import _split

from tests.unit.board.test_native import native_root, write_task

LANES = ["Waiting", "Ready", "In Progress", "Done"]
MACHINE = """\
name: board
states:
  waiting: {initial: true, waits: {criteria_met: CRITERIA_MET}}
  ready: {role: waiting_on_fact, waits: {criteria_unmet: CRITERIA_UNMET}}
  in_progress: {role: resting}
  done: {final: true}
events:
  CRITERIA_MET: [{from: waiting, to: ready}]
  CRITERIA_UNMET: [{from: ready, to: waiting}]
  CLAIM: [{from: ready, to: in_progress}]
  FINISH: [{from: in_progress, to: done}]
"""
CRITERIA = "\n## Start Criteria\n\n```yaml\nstart_criteria:\n  - {id: up, kind: cmd, expr: 'true'}\n```\n"


def _board(base: Path):
    native_root(base).mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(yaml.safe_dump({"project_name": "demo", "statuses": LANES}))
    write_task(base, "task-5", "In Progress")
    (base / "board.yaml").write_text(MACHINE)
    return board({"machine": "board.yaml"}, base)


def _front(path: Path) -> dict:
    return _split(path.read_text())[0]


def test_an_archive_removes_the_task_from_each_open_dependent_and_names_them(tmp_path: Path) -> None:
    built = _board(tmp_path)
    kept = write_task(tmp_path, "task-8", "In Progress", dependencies="[TASK-5, task-2]")
    emptied = write_task(tmp_path, "task-9", "Ready", dependencies="[task-5]")

    result = built.archive("task-5", "obsolete")

    assert result.ok
    assert "task-8" in result.output and "task-9" in result.output
    assert (native_root(tmp_path) / "archive" / "tasks" / "task-5 - Title.md").exists()
    assert (_front(kept)["dependencies"], _front(emptied)["dependencies"]) == (["task-2"], [])
    assert "Removed dependency on task-5: archived (obsolete)" in kept.read_text()
    assert (_front(kept)["status"], _front(emptied)["status"]) == ("In Progress", "Ready")


def test_an_archive_drops_the_criteria_the_dependent_needed_of_the_archived_task(tmp_path: Path) -> None:
    built = _board(tmp_path)
    kept = write_task(
        tmp_path, "task-8", "Waiting", dependencies="[task-5, task-2]", dependency_needs="[TASK-5#2, task-2#1]"
    )

    assert built.archive("task-5", "obsolete").ok

    assert (_front(kept)["dependencies"], _front(kept)["dependency_needs"]) == (["task-2"], ["task-2#1"])


def test_an_archive_leaves_done_and_archived_dependents_as_they_are(tmp_path: Path) -> None:
    built = _board(tmp_path)
    done = write_task(tmp_path, "task-8", "Done", dependencies="[task-5]")
    gone = native_root(tmp_path) / "archive" / "tasks" / "task-9 - Title.md"
    gone.parent.mkdir(parents=True)
    gone.write_text("---\nid: task-9\ntitle: Title\nstatus: Waiting\ndependencies: [task-5]\n---\n")
    before = done.read_text(), gone.read_text()

    assert built.archive("task-5", "").ok

    assert (done.read_text(), gone.read_text()) == before


def test_an_archive_releases_a_waiting_dependent_it_left_with_no_dependency_and_no_start_criteria(
    tmp_path: Path,
) -> None:
    built = _board(tmp_path)
    released = write_task(tmp_path, "task-7", "Waiting", dependencies="[task-5]")
    still_gated = write_task(tmp_path, "task-8", "Waiting", dependencies="[task-5, task-2]")
    criteria = write_task(tmp_path, "task-9", "Waiting", dependencies="[task-5]")
    criteria.write_text(criteria.read_text() + CRITERIA)

    assert built.archive("task-5", "").ok

    assert [_front(path)["status"] for path in (released, still_gated, criteria)] == ["Ready", "Waiting", "Waiting"]
