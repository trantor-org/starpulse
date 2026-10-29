"""Run one shard of the suite: the test files `SHARD_INDEX` (1-based) of `SHARD_COUNT` gets, the rest deselected.

CI's `python-shard` matrix sets both variables; unset, the whole suite runs. Files are never split between shards.
Every shard collects the same items, so they agree on the split without coordinating: files go heaviest first to the
lightest shard.
"""

from __future__ import annotations

import ast
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

#: Seconds of CPU a slow file takes in CI, summed over its setup, call and teardown (`pytest --durations=0`, 4 workers).
#: A file absent here, new or fast, weighs `UNMEASURED` per test. Stale numbers only unbalance the shards; each file
#: still runs once. `test_agent_cli.py` is weighted above its 306 CPU seconds: the shard that held it ran 162-175 s while
#: the rest ran 75-95 s, so it gets a shard to itself.
SECONDS = {
    "tests/integration/cli/test_agent_cli.py": 600,
    "tests/integration/flow_metrics/test_history.py": 131,
    "tests/integration/server/test_api_contract.py": 120,
    "tests/integration/event_log/test_event_log.py": 59,
    "tests/unit/flow_metrics/test_history_summaries.py": 55,
    "tests/unit/runs/test_dagu_runs.py": 34,
    "tests/integration/server/test_standalone.py": 33,
    "ci/test_soak.py": 25,
    "tests/integration/server/test_write_guard.py": 23,
    "tests/integration/board/test_board_resume.py": 21,
    "tests/integration/flow_metrics/test_history_http.py": 20,
    "tests/unit/server/test_flow_reads.py": 16,
    "tests/integration/server/test_http.py": 13,
    "ci/test_latency_gate.py": 13,
    "tests/integration/scheduler/test_scheduler_served.py": 11,
    "tests/unit/board/test_lane_history_dedupe.py": 11,
}
UNMEASURED = 0.3
#: A shard this light, about 30 unmeasured tests, runs in one process: two xdist workers cost more in startup than they save.
SMALL_SHARD_SECONDS = 9
#: Cases a `parametrize` over something other than a literal list is assumed to make.
UNKNOWN_CASES = 5


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


def _cases(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    cases = 1
    for decorator in function.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        if call is None or not ast.unparse(call.func).endswith("parametrize"):
            continue
        values = call.args[1] if len(call.args) > 1 else None
        cases *= len(values.elts) if isinstance(values, ast.List | ast.Tuple) else UNKNOWN_CASES
    return cases


def count_tests(path: Path) -> int:
    """The tests a file collects, read from its source: a `parametrize` over a literal list counts its cases."""
    functions = (
        n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    return sum(_cases(function) for function in functions if function.name.startswith("test"))


def is_small(index: int, count: int, targets: Sequence[str], root: Path = Path()) -> bool:
    """Whether shard `index` of `count` over the test files `targets` weighs at most `SMALL_SHARD_SECONDS`.

    It reads the files rather than collecting them, so the answer comes before pytest starts; it splits as the plugin does.
    A target that is not a file (none, a directory, a node id) is not small.
    """
    if not targets or not all((root / target).is_file() for target in targets):
        return False
    weights = weigh({target: count_tests(root / target) for target in targets})
    return sum(weights[file] for file in assign(weights, count)[index - 1]) <= SMALL_SHARD_SECONDS


def pytest_collection_modifyitems(config, items):
    index, count = os.environ.get("SHARD_INDEX"), os.environ.get("SHARD_COUNT")
    if not index or not count:
        return
    files = [str(Path(item.path).relative_to(config.rootpath)) for item in items]
    mine = assign(weigh(Counter(files)), int(count))[int(index) - 1]
    kept = [item for item, file in zip(items, files) if file in mine]
    config.hook.pytest_deselected(items=[item for item, file in zip(items, files) if file not in mine])
    items[:] = kept


if __name__ == "__main__" and sys.argv[1:] == ["--small"]:
    index, count = os.environ.get("SHARD_INDEX"), os.environ.get("SHARD_COUNT")
    small = bool(index and count) and is_small(int(index), int(count), os.environ.get("PYTEST_TARGETS", "").split())
    raise SystemExit(0 if small else 1)
