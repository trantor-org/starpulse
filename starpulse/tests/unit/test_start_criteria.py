"""A task's Start Criteria on its record: parsed from the description, evaluated by the `[board] criteria` command."""

import json
import shlex
import sys
import time
from pathlib import Path

from starpulse import criteria
from starpulse.adapters.boards import native
from starpulse.adapters.boards.seam import TaskReader

TASK = """---
id: task-7
title: Wait for the soak
status: Waiting
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Check after the soak.

## Start Criteria

```yaml
start_criteria:
- id: soak-24h
  kind: prom
  expr: time()
  at_least: 1790000000
- id: rows
  kind: sql
  query: select count(*) from runs
  equals: 3
```
<!-- SECTION:DESCRIPTION:END -->
"""

EVALUATED = [
    {
        "id": "soak-24h",
        "kind": "prom",
        "expr": "time()",
        "at_least": 1790000000,
        "status": "met",
        "observed": 1790000100,
        "error": None,
        "checked_at": "2026-10-07T13:00:00-07:00",
    },
    {
        "id": "rows",
        "kind": "sql",
        "expr": "select count(*) from runs",
        "equals": 3,
        "status": "not-met",
        "observed": 2,
        "error": None,
        "checked_at": "2026-10-07T13:00:00-07:00",
    },
]


def _reader(tmp_path: Path, command: str | None, **settings: object) -> TaskReader:
    """The native board's reader over one task file, with `command` as the `[board] criteria` evaluator."""
    tasks = tmp_path / ".starpulse" / "board" / "tasks"
    built = native.board({"criteria": command, **settings} if command else {}, tmp_path)
    (tasks / "task-7 - Wait.md").write_text(TASK)
    assert built.read is not None
    return built.read


def _script(tmp_path: Path, body: str) -> str:
    """An evaluator command that runs `body` (Python) with the task id as `sys.argv[1]`."""
    path = tmp_path / "evaluator.py"
    path.write_text(body)
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(path))} {{id}}"


def test_a_configured_evaluator_gives_each_criterion_its_status_and_the_fields_it_was_authored_with(
    tmp_path: Path,
) -> None:
    command = _script(tmp_path, f"import json\nprint(json.dumps({EVALUATED!r}))\n")

    record = _reader(tmp_path, command)("task-7")

    assert record is not None
    assert [(c["id"], c["kind"], c["expr"], c["status"]) for c in record["start_criteria"]] == [
        ("soak-24h", "prom", "time()", "met"),
        ("rows", "sql", "select count(*) from runs", "unmet"),
    ]
    first, second = record["start_criteria"]
    assert (first["cmp"], first["want"], first["observed"]) == ("at_least", 1790000000, 1790000100)
    assert (second["cmp"], second["want"], second["observed"]) == ("equals", 3, 2)
    assert first["checked"] == "2026-10-07T13:00:00-07:00"
    assert first["error"] is None


def test_the_evaluator_is_given_the_task_id_and_its_unmet_exit_status_does_not_hide_its_results(
    tmp_path: Path,
) -> None:
    command = _script(
        tmp_path,
        f"import json, sys\nassert sys.argv[1] == 'task-7'\nprint(json.dumps({EVALUATED!r}))\nsys.exit(1)\n",
    )

    record = _reader(tmp_path, command)("task-7")

    assert record is not None
    assert [c["status"] for c in record["start_criteria"]] == ["met", "unmet"]


def test_with_no_evaluator_configured_each_criterion_is_not_evaluated(tmp_path: Path) -> None:
    record = _reader(tmp_path, None)("task-7")

    assert record is not None
    assert [(c["id"], c["status"], c["observed"], c["checked"]) for c in record["start_criteria"]] == [
        ("soak-24h", "not evaluated", None, None),
        ("rows", "not evaluated", None, None),
    ]


def test_a_task_without_a_start_criteria_block_has_none(tmp_path: Path) -> None:
    reader = _reader(tmp_path, None)
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-7 - Wait.md").write_text(
        "---\nid: task-7\ntitle: Plain\nstatus: Ready\n---\n\n## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\nNo gate.\n<!-- SECTION:DESCRIPTION:END -->\n"
    )

    record = reader("task-7")

    assert record is not None
    assert record["start_criteria"] == []


def test_an_evaluator_that_exits_non_zero_marks_every_criterion_error_with_its_message(tmp_path: Path) -> None:
    command = _script(tmp_path, "import sys\nprint('prometheus is down', file=sys.stderr)\nsys.exit(2)\n")

    record = _reader(tmp_path, command)("task-7")

    assert record is not None
    assert [c["status"] for c in record["start_criteria"]] == ["error", "error"]
    assert all("prometheus is down" in c["error"] for c in record["start_criteria"])
    assert [c["id"] for c in record["start_criteria"]] == ["soak-24h", "rows"]


def test_an_evaluator_that_prints_no_json_marks_every_criterion_error(tmp_path: Path) -> None:
    command = _script(tmp_path, "print('not json')\n")

    record = _reader(tmp_path, command)("task-7")

    assert record is not None
    assert [c["status"] for c in record["start_criteria"]] == ["error", "error"]


def test_an_evaluator_that_times_out_marks_every_criterion_error_and_the_record_still_builds(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(criteria, "TIMEOUT", 0.2)
    command = _script(tmp_path, "import time\ntime.sleep(5)\n")

    started = time.monotonic()
    record = _reader(tmp_path, command)("task-7")

    assert time.monotonic() - started < 3
    assert record is not None
    assert record["title"] == "Wait for the soak"
    assert [c["status"] for c in record["start_criteria"]] == ["error", "error"]
    assert all("timed out" in c["error"] for c in record["start_criteria"])


def test_an_evaluator_that_cannot_start_marks_every_criterion_error(tmp_path: Path) -> None:
    record = _reader(tmp_path, "/nonexistent/evaluator {id}")("task-7")

    assert record is not None
    assert [c["status"] for c in record["start_criteria"]] == ["error", "error"]


def test_a_second_read_inside_the_cache_window_does_not_run_the_evaluator_again(tmp_path: Path) -> None:
    runs = tmp_path / "runs.txt"
    command = _script(
        tmp_path,
        f"import json\nopen({str(runs)!r}, 'a').write('x')\nprint(json.dumps({EVALUATED!r}))\n",
    )
    read = _reader(tmp_path, command)

    first, second = read("task-7"), read("task-7")

    assert first == second
    assert runs.read_text() == "x"


def test_a_read_after_the_cache_window_runs_the_evaluator_again(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs.txt"
    command = _script(
        tmp_path,
        f"import json\nopen({str(runs)!r}, 'a').write('x')\nprint(json.dumps({EVALUATED!r}))\n",
    )
    now = [100.0]
    monkeypatch.setattr(criteria, "_clock", lambda: now[0])
    read = _reader(tmp_path, command)

    read("task-7")
    now[0] += criteria.CACHE_SECONDS + 1
    read("task-7")

    assert runs.read_text() == "xx"


def test_json_without_a_result_for_a_criterion_marks_that_criterion_error(tmp_path: Path) -> None:
    command = _script(tmp_path, f"import json\nprint(json.dumps({EVALUATED[:1]!r}))\n")

    record = _reader(tmp_path, command)("task-7")

    assert record is not None
    assert [c["status"] for c in record["start_criteria"]] == ["met", "error"]
    assert "rows" in record["start_criteria"][1]["error"]


def test_the_criteria_setting_is_a_known_board_setting(tmp_path: Path) -> None:
    built = native.board({"criteria": "evaluate {id}"}, tmp_path)

    assert built.read is not None
    assert json.loads(json.dumps(built.read("task-404"))) is None
