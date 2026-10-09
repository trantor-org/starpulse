"""The consumer-pattern page's example runs: it tails the log into a SQLite sink and resumes from the sink's cursor."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.eventlog import events, lane_events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.runs import run_events
from starpulse.contracts import BoardTask

PAGE = next(root for root in Path(__file__).resolve().parents if (root / "README.md").is_file()) / "docs/consumers.md"


@pytest.fixture
def example() -> dict[str, Any]:
    """The page's first Python block, executed as a module."""
    blocks = re.findall(r"```python\n(.*?)```", PAGE.read_text() if PAGE.is_file() else "", re.DOTALL)
    assert blocks, f"{PAGE.name} has no Python example"
    namespace: dict[str, Any] = {}
    exec(compile(blocks[0], PAGE.name, "exec"), namespace)  # noqa: S102 - the page's own example, under test
    return namespace


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


def _write_one_of_each(log: EventLog) -> None:
    task = BoardTask(id="T-1", title="t", team="core", lane="in_progress")
    events.publish("in-progress", "WORKTREE_READY", actor="agent", task="T-1", now=5.0, log=log)
    lane_events.publish(log, "T-1@in_progress@5.0", task, 5.0)
    log.append(run_events.STREAM, run_events.entry("start", "nightly", "r1", "running", now=6.0))


def _rows(sink: Any) -> list[tuple[str, dict]]:
    return [(stream, json.loads(record)) for stream, record in sink.execute("SELECT stream, record FROM events ORDER BY at")]


def test_the_example_copies_each_stream_into_the_sink_as_its_validated_record(
    example: dict[str, Any], log: EventLog, tmp_path: Path
) -> None:
    _write_one_of_each(log)
    sink = example["open_sink"](str(tmp_path / "sink.sqlite"))

    assert example["drain"](log, sink) == 3

    assert [stream for stream, _ in _rows(sink)] == ["machine:events", "board:lanes", "runs:events"]
    assert _rows(sink)[1][1]["lane"] == "in_progress"


def test_the_example_resumes_after_the_cursor_it_kept_in_the_sink_and_never_copies_twice(
    example: dict[str, Any], log: EventLog, tmp_path: Path
) -> None:
    path = str(tmp_path / "sink.sqlite")
    _write_one_of_each(log)
    first = example["open_sink"](path)
    assert example["drain"](log, first) == 3
    first.close()

    log.append(run_events.STREAM, run_events.entry("end", "nightly", "r1", "succeeded", now=7.0))
    second = example["open_sink"](path)  # a new process: only the sink's own cursor says where to resume

    assert example["drain"](log, second) == 1
    assert example["drain"](log, second) == 0
    assert len(_rows(second)) == 4
