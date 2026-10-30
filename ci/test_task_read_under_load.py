"""`GET /api/task/<id>` reads a task's file from the native board; a read of a task the board has not served yet must
answer within the page's budget (50 ms at p95) while the host is overloaded. Nightly, as it holds the host at twice its
cores of busy processes for the length of the run.

The reader is the route's whole compute (`task_record` is a held-check, this read and the cited pulls): the board is
1,500 task files, the size of the live board, and every read names a task not read before, as a viewer opening cards in
turn does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from time import perf_counter

import pytest
import yaml
from starpulse.board.adapters.native import board

pytestmark = [pytest.mark.nightly, pytest.mark.slow]

TASKS = 1500
READS = 200
BUDGET_MS = 50.0


def _seed(base: Path) -> list[str]:
    root = base / ".starpulse" / "board"
    (root / "tasks").mkdir(parents=True)
    (root / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": ["To Do", "In Progress", "Done"], "task_prefix": "task"})
    )
    for number in range(1, TASKS + 1):
        (root / "tasks" / f"task-{number} - Title.md").write_text(
            f"---\nid: task-{number}\ntitle: Title\nstatus: To Do\n---\n\n"
            "<!-- SECTION:DESCRIPTION:BEGIN -->\nWhy\n<!-- SECTION:DESCRIPTION:END -->\n"
        )
    return [f"task-{number}" for number in range(1, TASKS + 1, TASKS // READS)]


@pytest.fixture
def host_overloaded() -> Iterator[None]:
    """Twice as many busy processes as cores, so the reader runs on a host at load 2 per core."""
    burners = [
        subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(2 * (os.cpu_count() or 1))
    ]
    try:
        yield
    finally:
        for burner in burners:
            burner.kill()
        for burner in burners:
            burner.wait()


def test_a_first_read_of_each_task_stays_within_the_budget_while_the_host_is_overloaded(
    tmp_path: Path, host_overloaded: None
) -> None:
    ids = _seed(tmp_path)
    read = board({}, tmp_path).read
    assert read is not None
    took_ms: list[float] = []
    for task in ids:
        started = perf_counter()
        record = read(task)
        took_ms.append((perf_counter() - started) * 1000)
        assert record is not None
    took_ms.sort()
    p95 = took_ms[int(len(took_ms) * 0.95) - 1]
    assert p95 < BUDGET_MS, f"p95 {p95:.1f} ms over {len(ids)} first reads of {TASKS} tasks, budget {BUDGET_MS} ms"
