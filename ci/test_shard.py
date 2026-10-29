"""Sharding the suite across CI jobs: every test file lands in exactly one shard, and the shards stay balanced."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from shard import SECONDS, SMALL_SHARD_SECONDS, UNMEASURED, assign, count_tests, is_small, weigh

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
    weights = weigh({slow: 3, "tests/new/test_new.py": 10})
    assert weights[slow] == SECONDS[slow]
    assert 0 < weights["tests/new/test_new.py"] < SECONDS[slow]


def test_the_measured_files_are_spread_over_the_shards():
    heaviest = sorted(SECONDS, key=SECONDS.get, reverse=True)[:6]
    shards = assign(weigh(dict.fromkeys(heaviest, 1)), 6)
    assert all(len(shard) == 1 for shard in shards)


def collected(tree: Path, **env: str) -> int:
    """The number of tests pytest collects in `tree` with the `shard` plugin and the given shard environment."""
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "shard", "-p", "no:cacheprovider"],
        cwd=tree,
        env={
            **os.environ,
            "PYTHONPATH": str(CI),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",  # xdist, cov, memray and timeout shard no test; a quarter of each launch
            "PYTEST_ADDOPTS": "",  # CI's `-n`/`--dist` need the xdist this child does not load
            "SHARD_INDEX": "",
            "SHARD_COUNT": "",
            **env,
        },
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
    shard_envs = [{"SHARD_INDEX": str(i), "SHARD_COUNT": "3"} for i in (1, 2, 3)]
    with ThreadPoolExecutor() as pool:  # the four launches overlap: each is a subprocess, so the wall is one launch
        whole, *shards = pool.map(lambda env: collected(tmp_path, **env), [{}, *shard_envs])
    assert whole == 15
    assert sum(shards) == whole


def _write(root: Path, name: str, source: str) -> str:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(source)
    return name


def test_a_file_counts_its_tests_and_a_literal_parametrize_counts_its_cases(tmp_path):
    name = _write(
        tmp_path,
        "test_x.py",
        "import pytest\n\n\ndef helper(): ...\n\n\ndef test_a(): ...\n\n\nclass TestB:\n    def test_b(self): ...\n\n\n"
        "@pytest.mark.parametrize('n', [1, 2, 3])\ndef test_c(n): ...\n",
    )
    assert count_tests(tmp_path / name) == 5


def test_a_shard_of_under_thirty_unmeasured_tests_is_small_and_a_measured_slow_file_is_not(tmp_path):
    few = _write(tmp_path, "tests/test_few.py", "".join(f"def test_{i}(): ...\n" for i in range(29)))
    many = _write(tmp_path, "tests/test_many.py", "".join(f"def test_{i}(): ...\n" for i in range(31)))
    slow = next(iter(SECONDS))
    _write(tmp_path, slow, "def test_slow(): ...\n")
    assert 29 * UNMEASURED <= SMALL_SHARD_SECONDS < 31 * UNMEASURED
    assert is_small(1, 1, [few], tmp_path)
    assert not is_small(1, 1, [many], tmp_path)
    assert not is_small(1, 1, [few, slow], tmp_path)


def test_a_shard_is_small_by_the_files_it_is_assigned_not_by_the_whole_selection(tmp_path):
    big = _write(tmp_path, "tests/test_big.py", "".join(f"def test_{i}(): ...\n" for i in range(200)))
    small = _write(tmp_path, "tests/test_small.py", "def test_a(): ...\n")
    holders = [index for index in (1, 2) if is_small(index, 2, [big, small], tmp_path)]
    assert len(holders) == 1
    assert [i for i in (1, 2) if small in assign(weigh({big: 200, small: 1}), 2)[i - 1]] == holders


@pytest.mark.parametrize("targets", [[], ["tests"], ["tests/test_a.py::test_x"], ["tests/test_missing.py"]])
def test_no_target_a_directory_a_node_id_or_a_missing_file_is_not_small(tmp_path, targets):
    _write(tmp_path, "tests/test_a.py", "def test_x(): ...\n")
    assert not is_small(1, 1, targets, tmp_path)


def _shard_job(tmp_path: Path, targets: list[str], shard: tuple[int, int] | None) -> str:
    """The `PYTEST_ADDOPTS` ci/run.sh's `python-shard` hands pytest, with `uv` stubbed: `uv run ... python` runs the real
    Python, `uv run ... pytest` records the options, and `uv sync` does nothing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    seen = tmp_path / "addopts"
    stub = bin_dir / "uv"
    stub.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        f'  *pytest*) echo "$PYTEST_ADDOPTS" > {seen} ;;\n'
        f'  *"run --no-sync python"*) shift 3; exec {sys.executable} "$@" ;;\nesac\n'
    )
    stub.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "PYTEST_TARGETS": " ".join(targets), "SHARD_LOG": str(tmp_path / "log")}
    if shard:
        env |= {"SHARD_INDEX": str(shard[0]), "SHARD_COUNT": str(shard[1])}
    subprocess.run([str(CI / "run.sh"), "python-shard"], env=env, check=True, capture_output=True, text=True)
    return seen.read_text().strip()


def test_a_small_shard_runs_pytest_without_xdist_workers(tmp_path):
    few = "ci/test_xdist_workers.py"
    assert count_tests(CI.parent / few) * UNMEASURED <= SMALL_SHARD_SECONDS
    assert _shard_job(tmp_path, [few], (1, 1)) == ""


def test_a_heavy_shard_a_whole_suite_run_and_an_unsharded_run_keep_their_xdist_workers(tmp_path):
    slow = next(iter(SECONDS))
    assert _shard_job(tmp_path, [slow], (1, 1)).startswith("-n ")
    assert _shard_job(tmp_path, [], (1, 1)).startswith("-n ")
    assert _shard_job(tmp_path, ["ci/test_xdist_workers.py"], None).startswith("-n ")
