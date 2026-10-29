"""ci/coverage_map.py: the per-test coverage map the nightly suite publishes and the select step reads."""

import json
import subprocess
from pathlib import Path

import coverage
import coverage_map
import pytest


def _data(path: Path, root: Path, measured: dict[str, list[str]]) -> Path:
    """A coverage data file recording, per test context, the source files it executed."""
    data = coverage.CoverageData(str(path))
    for context, files in measured.items():
        data.set_context(context)
        data.add_lines({str(root / name): [1, 2] for name in files})
    data.write()
    return path


def test_build_maps_each_test_to_the_files_it_ran_with_phases_merged(tmp_path):
    data = _data(
        tmp_path / ".coverage",
        tmp_path,
        {
            "ci/test_a.py::test_one|setup": ["pkg/a.py"],
            "ci/test_a.py::test_one|run": ["pkg/b.py", "pkg/a.py"],
            "ci/test_b.py::test_two|run": ["pkg/c.py"],
            "": ["pkg/import_time.py"],
        },
    )

    collected = ["ci/test_a.py::test_one", "ci/test_b.py::test_two", "ci/test_b.py::test_never_ran"]

    built = coverage_map.build(data, tmp_path, sha="abc123", collected=collected)

    assert built == {
        "sha": "abc123",
        "collected": 3,
        "tests": {
            "ci/test_a.py::test_one": ["pkg/a.py", "pkg/b.py"],
            "ci/test_b.py::test_two": ["pkg/c.py"],
        },
    }


def test_a_parametrized_case_with_no_context_of_its_own_takes_its_functions_files(tmp_path):
    data = _data(tmp_path / ".coverage", tmp_path, {"ci/test_a.py::test_one[1]|run": ["pkg/a.py"]})
    collected = [f"ci/test_a.py::test_one[{case}]" for case in (1, 2, 3)]

    built = coverage_map.build(data, tmp_path, sha="abc", collected=collected)

    assert built["tests"] == {nodeid: ["pkg/a.py"] for nodeid in collected}


def test_build_keeps_the_relative_paths_of_combined_shard_data_and_skips_files_outside_the_root(tmp_path):
    data = coverage.CoverageData(str(tmp_path / ".coverage"))
    data.set_context("ci/test_a.py::test_one|run")
    data.add_lines({"pkg/a.py": [1], "/elsewhere/site.py": [1]})
    data.write()

    built = coverage_map.build(tmp_path / ".coverage", tmp_path, sha="abc", collected=["ci/test_a.py::test_one"])

    assert built["tests"] == {"ci/test_a.py::test_one": ["pkg/a.py"]}


def test_publish_then_latest_reads_the_newest_map_with_its_sha(tmp_path):
    first = {"sha": "aaa", "collected": 1, "tests": {"t": ["f.py"]}}
    second = {"sha": "bbb", "collected": 2, "tests": {"t": ["g.py"], "u": ["g.py"]}}

    coverage_map.publish(first, tmp_path / "maps")
    coverage_map.publish(second, tmp_path / "maps")

    assert coverage_map.latest(tmp_path / "maps") == second
    assert json.loads((tmp_path / "maps" / "aaa.json").read_text()) == first


def test_latest_is_none_before_any_nightly_published(tmp_path):
    assert coverage_map.latest(tmp_path / "maps") is None


def test_ratio_is_the_share_of_collected_tests_the_map_covers():
    assert coverage_map.ratio({"collected": 4, "tests": {"a": [], "b": [], "c": []}}) == pytest.approx(0.75)


def test_cli_build_publishes_and_latest_prints_sha_and_coverage(tmp_path, capsys):
    data = _data(tmp_path / ".coverage", tmp_path, {"t1|run": ["a.py"], "t2[a, b]|run": ["a.py"]})
    out = tmp_path / "maps"

    collected = tmp_path / "collected.txt"
    collected.write_text("t1\nt2[a, b]\n")

    coverage_map.main(
        ["build", str(data), "--root", str(tmp_path), "--sha", "abc", "--collected", str(collected), "--out", str(out)]
    )
    coverage_map.main(["latest", "--out", str(out)])

    assert capsys.readouterr().out.splitlines()[-1] == "abc 2/2 tests 100.0%"


def test_cli_build_records_the_contributing_shards_beside_the_sha(tmp_path):
    data = _data(tmp_path / ".coverage", tmp_path, {"t1|run": ["a.py"], "t2|run": ["a.py"]})
    out = tmp_path / "maps"
    collected = tmp_path / "collected.txt"
    collected.write_text("t1\nt2\n")

    coverage_map.main(
        ["build", str(data), "--root", str(tmp_path), "--sha", "abc", "--collected", str(collected), "--out", str(out)]
        + ["--shards", "0", "2", "--shard-count", "3"]
    )

    published = coverage_map.latest(out)
    assert (published["sha"], published["shards"], published["shard_count"]) == ("abc", ["0", "2"], 3)
    assert published["tests"] == {"t1": ["a.py"], "t2": ["a.py"]}


def test_cli_build_publishes_nothing_when_the_data_names_too_few_of_the_collected_tests(tmp_path, capsys):
    data = _data(tmp_path / ".coverage", tmp_path, {"t1|run": ["a.py"]})
    out = tmp_path / "maps"
    collected = tmp_path / "collected.txt"
    collected.write_text("t1\nt2\nt3\nt4\nt5\n")

    code = coverage_map.main(
        ["build", str(data), "--root", str(tmp_path), "--sha", "abc", "--collected", str(collected), "--out", str(out)]
    )

    assert code == 1
    assert coverage_map.latest(out) is None
    assert "20.0%" in capsys.readouterr().err


def test_facts_name_the_maps_sha_its_age_and_the_source_files_the_checkout_lost(tmp_path):
    root = tmp_path / "checkout"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "kept.py").write_text("")
    published = {"sha": "abc", "collected": 1, "tests": {"t": ["pkg/kept.py", "pkg/moved.py"]}}
    coverage_map.publish(published, tmp_path / "maps")
    stamp = (tmp_path / "maps" / "latest.json").stat().st_mtime

    facts = coverage_map.facts(published, tmp_path / "maps", root, now=stamp + 5 * 3600)

    assert facts == {"sha": "abc", "age_hours": 5.0, "files": 2, "missing": 1}


def test_facts_count_a_file_that_moved_since_the_maps_sha_as_present_and_a_deleted_one_as_missing(tmp_path):
    root = tmp_path / "checkout"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "moved.py").write_text("x = 1\n" * 20)
    (root / "pkg" / "deleted.py").write_text("y = 2\n" * 20)
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "map built"], check=True)
    built_at = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    (root / "sub").mkdir()
    subprocess.run([*git, "mv", "pkg/moved.py", "sub/moved.py"], check=True)
    subprocess.run([*git, "rm", "-q", "pkg/deleted.py"], check=True)
    subprocess.run([*git, "commit", "-qm", "move and delete"], check=True)
    published = {"sha": built_at, "collected": 1, "tests": {"t": ["pkg/moved.py", "pkg/deleted.py"]}}
    coverage_map.publish(published, tmp_path / "maps")

    assert coverage_map.facts(published, tmp_path / "maps", root)["missing"] == 1
