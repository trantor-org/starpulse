"""The server's read paths hold a bounded heap: reading every board task, every cited pull request and the whole
telemetry history, again and again, leaves the traced heap within a budget, so a cache that grows with what it has read
fails here before it wedges the live server (TASK-10294: 8.9 GB against a 8 GB `MemoryHigh`)."""

from __future__ import annotations

import gc
import json
import os
import tracemalloc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine
from starpulse.board.adapters.native import board
from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog
from starpulse.pulls.adapters.outbound.pulls import PullStore

MB = 1024 * 1024
PASSES = 3  # the first read fills a cache, the next two show whether it keeps growing

TASKS = 700
TASK_TEXT = 8_000  # characters of description, as a task with a long plan and notes has

PULLS = 300
PULL_BODY = 10_000
PULL_DETAIL = 8_000
REPO = "acme/widgets"

SIGNALS = 6_000
SIGNAL_BYTES = 900  # what one held signal may cost, of the ~3.7 KB the live server paid for each


MACHINE = """\
name: board
states:
  to_do: {initial: true}
  done: {final: true}
events:
  to_done: [{from: to_do, to: done}]
"""


@contextmanager
def traced() -> Iterator[Callable[[], float]]:
    """Yield a function giving the MB the traced heap has grown by since the block began."""
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    try:
        yield lambda: (gc.collect(), (tracemalloc.get_traced_memory()[0] - base) / MB)[1]
    finally:
        tracemalloc.stop()


def _board(base: Path) -> Any:
    root = base / ".starpulse" / "board"
    (root / "tasks").mkdir(parents=True)
    (base / "board.yaml").write_text(MACHINE)
    (root / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": ["To Do", "Done"], "task_prefix": "task"})
    )
    text = "word " * (TASK_TEXT // 5)
    for number in range(1, TASKS + 1):
        path = root / "tasks" / f"task-{number} - Title.md"
        path.write_text(
            f"---\nid: task-{number}\ntitle: Title\nstatus: To Do\n---\n\n"
            f"<!-- SECTION:DESCRIPTION:BEGIN -->\n{text}{number}\n<!-- SECTION:DESCRIPTION:END -->\n"
        )
        stamp = path.stat().st_mtime_ns - 10_000_000_000  # settled, so a record may be kept
        os.utime(path, ns=(stamp, stamp))
    return board({"machine": "board.yaml"}, base)


def _pull(number: int) -> dict[str, Any]:
    return {
        "repo": REPO,
        "number": number,
        "state": "MERGED",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": f"{number} " + "x" * PULL_BODY,
        "checks": "none",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": "2020-01-01T00:00:00Z",  # long past the window the store holds in memory
        "mergedAt": "2020-01-01T00:00:00Z",
        "mergeSha": None,
        "fetchedAt": 900.0,
        "detail": {"files": ["y" * 100] * (PULL_DETAIL // 100), "n": number},
    }


@pytest.mark.slow  # 15.2 s under the CI worker's load, over the gate's 15 s bound; the heap budget it asserts is unchanged
def test_reading_every_board_task_again_and_again_holds_the_heap_under_its_budget(tmp_path: Path) -> None:
    built = _board(tmp_path)
    assert built.read is not None

    with traced() as grown:
        for _ in range(PASSES):
            for number in range(1, TASKS + 1):
                assert built.read(f"task-{number}") is not None
        held = grown()

    # The kept records (256 of ~14 KB) settle near 3.6 MB; a loaded CI worker's other threads have pushed the traced
    # heap to 6.3. A cache keeping all 700 records holds ~9.8 MB, so 8 still fails it.
    assert held < 8, f"{held:.1f} MB of {TASKS} task files stay held after {PASSES} passes"


def test_reading_every_cited_pull_request_again_and_again_holds_the_heap_under_its_budget(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}")
    PullStore(engine).save([_pull(number) for number in range(1, PULLS + 1)])
    store = PullStore(engine)  # opens holding none of them: they are older than the window
    store.keep_listings()

    with traced() as grown:
        for _ in range(PASSES):
            for number in range(1, PULLS + 1):
                assert store.find(REPO, number)
                store.resident(REPO, number)
            store.find(REPO, state="MERGED")
        held = grown()

    assert held < 5, f"{held:.1f} MB of {PULLS} closed pull requests stay held after {PASSES} passes"


class _History:
    """A Loki that serves `SIGNALS` stored lines, whole through `fetch` or in pages through `pages`."""

    def fetch(self, after: int) -> list[tuple[int, dict[str, Any]]]:
        return [row for page in self.pages(after) for row in page]

    def pages(self, after: int) -> Iterator[list[tuple[int, dict[str, Any]]]]:
        for start in range(0, SIGNALS, 2000):
            yield [(n, self._row(n)) for n in range(start, min(start + 2000, SIGNALS))]

    @staticmethod
    def _row(n: int) -> dict[str, Any]:
        return json.loads(
            json.dumps(  # a row decoded from a line, as Loki gives it: its strings are its own objects
                {
                    "harness": "claude-code",
                    "session": f"{n // 200:08x}-0000-4000-8000-000000000000",
                    "kind": "tool",
                    "time": 1_700_000_000.0 + n,
                    "key": f"claude-code:{n // 200:08x}-0000-4000-8000-000000000000:tool_result:{n}:2026-10-30T18:00:00",
                    "name": "Bash",
                    "model": "claude-opus-4-5",
                    "effort": "high",
                    "ok": True,
                    "origin": "main",
                    "agent": "",
                    "command": "ls",
                    "captured": True,
                    "detail": "",
                    "seconds": 0.5,
                    "input": 10,
                    "output": 20,
                    "cache_read": 30,
                    "cache_write": 40,
                    "reasoning": 0,
                    "cost": 0.01,
                    "activities": ["read", "write"],
                    "reads": [f"/srv/trantor/file-{n % 50}.py"],
                    "shell_write": False,
                    "writes": [],
                    "turn": f"turn-{n // 20}",
                    "label": "",
                    "eval": "",
                }
            )
        )


def test_the_held_telemetry_history_costs_a_bounded_number_of_bytes_a_signal() -> None:
    log = TelemetryLog(None, keep=1e12, loki=_History())  # type: ignore[arg-type]

    with traced() as grown:
        assert len(log.read()) == SIGNALS
        held = grown()

    assert held * MB / SIGNALS < SIGNAL_BYTES, f"{held * MB / SIGNALS:.0f} B a held signal"
