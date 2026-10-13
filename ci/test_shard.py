"""Sharding the suite across CI jobs: every test file lands in exactly one shard, and the shards stay balanced."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from shard import SECONDS, assign, weigh

CI = Path(__file__).resolve().parent


@pytest.mark.parametrize("count", [1, 2, 4, 7])
def test_every_file_lands_in_exactly_one_shard(count):
    weights = {f"test_{i}.py": (i * 37) % 11 + 1 for i in range(20)}
    shards = assign(weights, count)
    assert len(shards) == count
    assert sorted(file for shard in shards for file in shard) == sorted(weights)


def test_shards_are_balanced_by_weight():
    weights = {"big.py": 10, "mid.py": 6, "a.py": 5, "b.py": 5, "c.py": 4, "d.py": 4, "e.py": 2, "f.py": 2}
    totals = [sum(weights[file] for file in shard) for shard in assign(weights, 3)]
    assert max(totals) - min(totals) <= 2


def test_the_split_does_not_depend_on_collection_order():
    weights = {f"test_{i}.py": i % 5 + 1 for i in range(12)}
    assert assign(weights, 3) == assign(dict(reversed(weights.items())), 3)


def test_a_file_weighs_its_measured_seconds_and_an_unmeasured_one_its_test_count():
    slow = next(iter(SECONDS))
    weights = weigh({slow: 3, "starpulse/tests/new/test_new.py": 10})
    assert weights[slow] == SECONDS[slow]
    assert 0 < weights["starpulse/tests/new/test_new.py"] < SECONDS[slow]


def test_the_measured_files_are_spread_over_the_shards():
    heaviest = sorted(SECONDS, key=SECONDS.get, reverse=True)[:5]
    shards = assign(weigh(dict.fromkeys(heaviest, 1)), 5)
    assert all(len(shard) == 1 for shard in shards)


def collected(tree: Path, **env: str) -> int:
    """The number of tests pytest collects in `tree` with the `shard` plugin and the given shard environment."""
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "shard", "-p", "no:cacheprovider"],
        cwd=tree,
        env={**os.environ, "PYTHONPATH": str(CI), "SHARD_INDEX": "", "SHARD_COUNT": "", **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode in (0, 5), run.stdout + run.stderr  # 5: nothing collected
    count = re.search(r"(\d+)(?:/\d+)? tests? collected", run.stdout)  # "5/15 tests collected" when some are deselected
    return int(count.group(1)) if count else 0


def test_the_shards_of_a_tree_collect_exactly_the_tests_of_the_whole_tree(tmp_path):
    for i, tests in enumerate([5, 3, 3, 2, 1, 1]):
        body = "\n".join(f"def test_{j}():\n    pass\n" for j in range(tests))
        (tmp_path / f"test_file_{i}.py").write_text(body)
    whole = collected(tmp_path)
    assert whole == 15
    assert sum(collected(tmp_path, SHARD_INDEX=str(i), SHARD_COUNT="3") for i in (1, 2, 3)) == whole
