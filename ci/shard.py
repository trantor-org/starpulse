"""Run one shard of the suite: the test files `SHARD_INDEX` (1-based) of `SHARD_COUNT` gets, the rest deselected.

CI's `python-shard` matrix sets both variables; unset, the whole suite runs. Files are never split between shards.
Every shard collects the same items, so they agree on the split without coordinating: files go heaviest first to the
lightest shard.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

#: Seconds of CPU a slow file takes in CI, summed over its setup, call and teardown (`pytest --durations=0`, 4 workers).
#: A file absent here, new or fast, weighs `UNMEASURED` per test. Stale numbers only unbalance the shards; each file
#: still runs once. `test_agent_cli.py` is weighted above its 306 CPU seconds: the shard that held it ran 162-175 s while
#: the rest ran 75-95 s, so it gets a shard to itself.
SECONDS = {
    "starpulse/tests/integration/cli/test_agent_cli.py": 600,
    "starpulse/tests/integration/eventlog/test_history.py": 131,
    "starpulse/tests/integration/server/test_api_contract.py": 120,
    "starpulse/tests/integration/eventlog/test_event_log.py": 59,
    "starpulse/tests/unit/eventlog/test_history_summaries.py": 55,
    "starpulse/tests/unit/runs/test_dagu_runs.py": 34,
    "starpulse/tests/integration/server/test_standalone.py": 33,
    "ci/test_soak.py": 25,
    "starpulse/tests/integration/server/test_write_guard.py": 23,
    "starpulse/tests/integration/feed/test_board_resume.py": 21,
    "starpulse/tests/integration/eventlog/test_history_http.py": 20,
    "starpulse/tests/unit/server/test_flow_reads.py": 16,
    "starpulse/tests/integration/server/test_http.py": 13,
    "ci/test_latency_gate.py": 13,
    "starpulse/tests/integration/autopilot/test_autopilot_served.py": 11,
    "starpulse/tests/unit/feed/test_lane_history_dedupe.py": 11,
}
UNMEASURED = 0.3

def weigh(tests_per_file: dict[str, int]) -> dict[str, float]:
    return {file: SECONDS.get(file, tests * UNMEASURED) for file, tests in tests_per_file.items()}


def assign(weights: dict[str, float], count: int) -> list[set[str]]:
    """Split the files into `count` shards of near-equal total weight; the same input always gives the same split."""
    shards: list[set[str]] = [set() for _ in range(count)]
    totals = [0] * count
    for file in sorted(weights, key=lambda name: (-weights[name], name)):
        lightest = totals.index(min(totals))
        shards[lightest].add(file)
        totals[lightest] += weights[file]
    return shards


def pytest_collection_modifyitems(config, items):
    index, count = os.environ.get("SHARD_INDEX"), os.environ.get("SHARD_COUNT")
    if not index or not count:
        return
    files = [str(Path(item.path).relative_to(config.rootpath)) for item in items]
    mine = assign(weigh(Counter(files)), int(count))[int(index) - 1]
    kept = [item for item, file in zip(items, files) if file in mine]
    config.hook.pytest_deselected(items=[item for item, file in zip(items, files) if file not in mine])
    items[:] = kept
