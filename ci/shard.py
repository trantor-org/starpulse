"""Run one shard of the suite: the test files `SHARD_INDEX` (1-based) of `SHARD_COUNT` gets, the rest deselected.

CI's `python-shard` matrix sets both variables; unset, the whole suite runs. Files are never split, so a module-scoped
Postgres container starts in one shard only and an `xdist_group` stays on one worker. Every shard collects the same
items, so they agree on the split without coordinating: files go heaviest first to the lightest shard.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

#: Seconds of CPU a slow file takes, summed over its setup, call and teardown (`pytest --durations=0`, 3 workers). A file
#: absent here, new or fast, weighs `UNMEASURED` per test. Stale numbers only unbalance the shards; each file still runs once.
SECONDS = {
    "starpulse/tests/integration/cli/test_agent_cli.py": 357,
    "starpulse/tests/unit/server/test_flow_reads.py": 235,
    "starpulse/tests/integration/hub/test_oidc_gate.py": 153,
    "starpulse/tests/unit/hub/test_forwarder.py": 146,
    "starpulse/tests/integration/server/test_api_contract.py": 114,
    "starpulse/tests/integration/level/test_level_http.py": 104,
    "starpulse/tests/integration/hub/test_lane_forwarding.py": 75,
    "starpulse/tests/unit/server/test_forwarding_route.py": 61,
    "starpulse/tests/unit/eventlog/test_history_summaries.py": 59,
    "starpulse/tests/integration/hub/test_forwarding_kit.py": 59,
    "starpulse/tests/unit/level/test_insights_kit.py": 51,
    "starpulse/tests/integration/eventlog/test_history.py": 46,
    "starpulse/tests/unit/runs/test_triggers.py": 43,
    "starpulse/tests/integration/level/test_insights_http.py": 42,
    "ci/test_soak.py": 41,
    "starpulse/tests/unit/runs/test_dagu_runs.py": 36,
    "ci/test_select_tests.py": 34,
    "starpulse/tests/integration/server/test_write_guard.py": 34,
    "starpulse/tests/unit/pulls/test_pull_store.py": 30,
}
UNMEASURED = 0.17


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
