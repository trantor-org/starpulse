"""Which tests a pull request runs: those whose imports reach what it changed, the full suite when that is unknowable."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from coverage_map import publish
from select_tests import FULL, READERS, SHARD_COUNT, Selection, main, select, shards_for

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A package with a leaf module, a hub that imports it, an adapter loaded by name, and one test per module."""
    files = {
        "starpulse/__init__.py": "",
        "starpulse/leaf.py": "X = 1\n",
        "starpulse/lone.py": "Y = 2\n",
        "starpulse/_internal/board/seam.py": "import importlib\nfrom starpulse._internal.config.adapter_types import module_name\n",
        "starpulse/_internal/runs/dagu.py": "def start(): ...\ndef follow(): ...\n",
        "starpulse/_internal/config/adapter_types.py": 'BUILT_IN = {"dagu": "starpulse._internal.runs.dagu", "jira": "x"}\n',
        "starpulse/_internal/hub/__init__.py": "",
        "starpulse/_internal/server/server.py": "",
        "starpulse/_internal/hub/hub.py": "from starpulse import leaf\n",
        "starpulse/_internal/eventlog/migrations/versions/0001_initial.py": "",
        "starpulse/_internal/board/jira.py": "def board(settings, base):\n    return None\n",
        "starpulse/tests/__init__.py": "",
        "starpulse/tests/conftest.py": "",
        "starpulse/tests/helpers.py": "from starpulse import lone\n",
        "starpulse/tests/unit/feed/test_leaf.py": "from starpulse.leaf import X\n",
        "starpulse/tests/unit/hub/test_hub.py": "from starpulse._internal.hub import hub\n",
        "starpulse/tests/unit/feed/test_lone.py": "from starpulse.tests.helpers import lone\n",
        "starpulse/tests/unit/board/test_board.py": 'from starpulse._internal.board import seam\n\nKIND = "jira"\n',
        "starpulse/tests/unit/contracts/test_public_surface.py": "",
        "starpulse/tests/unit/contracts/test_neutrality.py": "",
        "starpulse/tests/unit/eventlog/test_consumer_pattern.py": "",
        "starpulse/tests/unit/config/test_builtin_types.py": "",
        "starpulse/contracts/__init__.py": "",
        "starpulse/contracts/api/__init__.py": "",
        "starpulse/contracts/api/schema.py": "",
        "starpulse/contracts/api/__main__.py": "",
        "starpulse/contracts/__main__.py": "",
        "starpulse/contracts/adapters.py": "",
        "starpulse/_internal/machines/machine_definition.py": "",
        "starpulse/tests/unit/contracts/test_contracts.py": "from starpulse.contracts import adapters\nfrom starpulse.contracts.api import schema\n",
        "starpulse/tests/unit/contracts/test_finding.py": "from starpulse.contracts import adapters\n",
        "starpulse/tests/unit/machines/test_machine_definition.py": "from starpulse._internal.machines import machine_definition\n",
        "starpulse/_internal/ci/ci.py": "",
        "starpulse/_internal/harnesses/harness.py": "",
        "starpulse/_internal/pulls/github.py": "",
        "starpulse/_internal/cli/skill_install.py": "",
        "starpulse/tests/unit/pulls/test_github.py": "from starpulse._internal.pulls import github\n",
        "starpulse/tests/unit/machines/test_github_pull_request_machine.py": "",
        "starpulse/tests/integration/cli/test_agent_cli.py": "from starpulse._internal.cli import skill_install\n",
        "ci/sizer.py": "",
        "ci/test_sizer.py": "from sizer import X\n",
        "ci/avoid_list.py": "",
        "ci/test_avoid_list.py": "import avoid_list\n",
        "ci/test_ic_imports.py": "",
        "ci/test_workflow_placement.py": "",
        "ci/ui_preview.py": "",
        "ci/test_page_latency.py": "",
        "ci/test_soak.py": "",
        "ci/test_load.py": "",
        "ci/test_ui_preview.py": "import ui_preview\n",
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return tmp_path


def test_a_changed_module_selects_the_tests_that_import_it_directly_or_through_another_module(repo):
    assert select(repo, ["starpulse/leaf.py"]) == Selection(
        ["starpulse/tests/unit/feed/test_leaf.py", "starpulse/tests/unit/hub/test_hub.py"]
    )


def test_a_changed_test_helper_selects_the_tests_that_import_it(repo):
    assert select(repo, ["starpulse/tests/helpers.py"]) == Selection(["starpulse/tests/unit/feed/test_lone.py"])


def test_a_changed_test_file_selects_itself(repo):
    assert select(repo, ["starpulse/tests/unit/feed/test_lone.py"]) == Selection(
        ["starpulse/tests/unit/feed/test_lone.py"]
    )


def test_a_ci_script_selects_the_ci_test_that_imports_it_by_its_bare_name(repo):
    assert select(repo, ["ci/sizer.py"]) == Selection(["ci/test_sizer.py"])


def test_an_adapter_selects_the_tests_of_the_loader_that_imports_it_by_name(repo):
    assert "starpulse/tests/unit/board/test_board.py" in select(repo, ["starpulse/_internal/board/jira.py"]).tests


def test_a_package_init_selects_every_test_under_the_package(repo):
    assert select(repo, ["starpulse/__init__.py"]) == Selection(
        sorted(str(p.relative_to(repo)) for p in (repo / "starpulse/tests").rglob("test_*.py"))
    )


def test_a_migration_selects_the_tests_of_the_module_that_runs_migrations(repo):
    assert select(repo, ["starpulse/_internal/eventlog/migrations/versions/0001_initial.py"]) == Selection(
        ["starpulse/tests/unit/hub/test_hub.py"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "starpulse/tests/conftest.py",
        "starpulse/tests/fixtures/jira/search_page_1.json",
        "starpulse/gone.py",  # deleted: what imported it is no longer in the graph
        "some/new/file.txt",
        "scripts/new_tool.py",
    ],
)
def test_a_change_whose_readers_the_graph_cannot_name_runs_the_full_suite(repo, path):
    assert select(repo, ["starpulse/lone.py", path]) == FULL


@pytest.mark.parametrize(
    ("path", "tests"),
    [
        ("README.md", ["ci/test_ui_preview.py"]),
        ("docs/public-surface.md", ["starpulse/tests/unit/contracts/test_public_surface.py"]),
        ("starpulse/web/src/App.tsx", ["ci/test_ui_preview.py", "starpulse/tests/unit/contracts/test_neutrality.py"]),
        ("docs/consumers.md", ["starpulse/tests/unit/eventlog/test_consumer_pattern.py"]),
        ("docs/serving.md", ["starpulse/tests/unit/config/test_builtin_types.py"]),
        ("docs/sources.md", ["starpulse/tests/unit/config/test_builtin_types.py"]),
        (
            ".github/workflows/ci.yml",
            [
                "ci/test_avoid_list.py",
                "ci/test_ic_imports.py",
                "ci/test_load.py",
                "ci/test_page_latency.py",
                "ci/test_sizer.py",
                "ci/test_soak.py",
                "ci/test_ui_preview.py",
                "ci/test_workflow_placement.py",
            ],
        ),
        ("bench/page_latency.py", ["ci/test_load.py", "ci/test_page_latency.py", "ci/test_soak.py"]),
        ("bench/soak.py", ["ci/test_soak.py"]),
        ("bench/load.py", ["ci/test_load.py"]),
        (
            "starpulse/machines/copilot.yaml",
            [
                "starpulse/tests/unit/machines/test_github_pull_request_machine.py",
                "starpulse/tests/unit/pulls/test_github.py",
            ],
        ),
        (
            "starpulse/skills/writing-starpulse-adapters/SKILL.md",
            ["starpulse/tests/integration/cli/test_agent_cli.py"],
        ),
        ("ci/static_checks.sh", ["ci/test_ic_imports.py", "ci/test_workflow_placement.py"]),
    ],
)
def test_a_mapped_non_python_file_selects_the_tests_that_read_it(repo, path, tests):
    assert select(repo, [path]) == Selection(tests)


@pytest.mark.parametrize(
    "path",
    [
        "CONTRIBUTING.md",
        "docs/development-loop.md",
        "docs/security.md",
        "LICENSE",
        ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/pull_request_template.md",
        "bench/hub_ingest.py",
        "bench/free_threading/run.sh",
    ],
)
def test_a_file_no_test_reads_selects_nothing(repo, path):
    assert select(repo, [path]) == Selection([])


def test_a_non_python_file_whose_mapped_reader_is_gone_runs_the_full_suite(repo):
    (repo / "starpulse/_internal/server/server.py").unlink()
    assert select(repo, ["README.md"]) == FULL


def test_a_deleted_test_file_selects_nothing(repo):
    assert select(repo, ["starpulse/tests/unit/feed/test_gone.py"]) == Selection([])


def test_a_module_replaced_by_a_package_selects_the_tests_that_import_the_package(repo):
    """`contracts/api.py` became `contracts/api/__init__.py`: its importers still import the name."""
    assert select(repo, ["starpulse/contracts/api.py"]) == Selection(
        ["starpulse/tests/unit/contracts/test_contracts.py"]
    )


def test_an_adapter_selects_a_subset_and_not_the_ci_tests(repo):
    selected = select(repo, ["starpulse/_internal/board/jira.py"]).tests
    assert "starpulse/tests/unit/board/test_board.py" in selected
    assert "ci/test_sizer.py" not in selected


def test_every_file_the_readers_map_names_exists_in_the_real_repository():
    """The one check the fixture repository cannot make: a stale entry sends `select` to the full suite for its file."""
    missing = [reader for readers in READERS.values() for reader in readers if not (ROOT / reader).is_file()]
    assert not missing


def test_a_diff_touching_a_python_source_file_selects_a_target_and_so_launches_a_shard(repo):
    """The blind spot of sizing the matrix from the selection: a selector that finds nothing turns a real change green."""
    for changed in ("ci/sizer.py", "starpulse/__init__.py"):
        selection = select(repo, [changed])
        assert selection.tests
        assert shards_for(selection)


@pytest.mark.parametrize(
    ("tests", "shards"),
    [
        ([], []),
        (["ci/test_a.py"], [1]),
        ([f"ci/test_{i}.py" for i in range(12)], [1]),  # 12 files at 5 s: one shard's worth of tests
        ([f"ci/test_{i}.py" for i in range(50)], [1, 2, 3, 4, 5]),
        ([f"ci/test_{i}.py" for i in range(500)], list(range(1, SHARD_COUNT + 1))),
        (["starpulse/tests/integration/cli/test_agent_cli.py"], [1]),  # one heavy file fills one shard, never two
        (
            [
                "starpulse/tests/integration/cli/test_agent_cli.py",
                "starpulse/tests/integration/level/test_level_http.py",
            ],
            [1, 2],
        ),
    ],
)
def test_a_selection_launches_a_shard_per_minute_of_its_tests_and_never_more_than_it_has_files(tests, shards):
    assert shards_for(Selection(tests)) == shards


def test_the_full_suite_launches_every_shard():
    assert shards_for(FULL) == list(range(1, SHARD_COUNT + 1)) == [1, 2, 3, 4, 5, 6]


def _printed(monkeypatch, capsys, repo, stdin: str, *args: str) -> dict[str, str]:
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    main(list(args))
    return dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())


def test_a_diff_selecting_no_test_prints_no_target_and_no_shard(monkeypatch, capsys, repo):
    printed = _printed(monkeypatch, capsys, repo, "CONTRIBUTING.md\n")
    assert printed["PYTEST_TARGETS"] == ""
    assert json.loads(printed["PYTEST_SHARDS"]) == []


def test_a_diff_selecting_a_test_prints_its_target_and_the_shards_it_needs(monkeypatch, capsys, repo):
    printed = _printed(monkeypatch, capsys, repo, "ci/sizer.py\n")
    assert "ci/test_sizer.py" in printed["PYTEST_TARGETS"].split()
    assert json.loads(printed["PYTEST_SHARDS"])


def test_a_diff_that_runs_the_full_suite_prints_no_target_and_every_shard(monkeypatch, capsys, repo):
    printed = _printed(monkeypatch, capsys, repo, "pyproject.toml\n")
    assert printed["PYTEST_TARGETS"] == ""
    assert json.loads(printed["PYTEST_SHARDS"]) == [1, 2, 3, 4, 5, 6]


def test_full_prints_every_shard_whatever_the_diff(monkeypatch, capsys, repo):
    """The nightly schedule and a manual dispatch have no diff: they read none and run everything."""
    printed = _printed(monkeypatch, capsys, repo, "", "--full")
    assert printed["PYTEST_TARGETS"] == ""
    assert json.loads(printed["PYTEST_SHARDS"]) == [1, 2, 3, 4, 5, 6]


def _ci() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]


def test_the_nightly_schedule_and_a_dispatch_select_everything_once_in_a_job():
    workflow = yaml.safe_load(CI.read_text())
    # PyYAML reads the bare `on:` key as True.
    # A pull request and a merge group run on Dagu; only a push, the schedule and a dispatch reach this workflow.
    assert set(workflow[True]) == {"push", "schedule", "workflow_dispatch"}
    job = workflow["jobs"]["select"]
    assert job["if"] == "github.event_name != 'push'"
    assert job["outputs"] == {
        "PYTEST_TARGETS": "${{ steps.select.outputs.PYTEST_TARGETS }}",
        "PYTEST_SHARDS": "${{ steps.select.outputs.PYTEST_SHARDS }}",
    }
    select_step = next(s for s in job["steps"] if s.get("id") == "select")
    # Only the nightly schedule and a dispatch reach this workflow, and neither has a diff: both select everything.
    assert select_step["run"] == 'uv run --no-sync python ci/select_tests.py --full >> "$GITHUB_OUTPUT"'


def test_the_import_layers_are_checked_once_in_the_select_job_not_in_every_shard():
    jobs = _ci()
    assert any("lint-imports" in s.get("run", "") for s in jobs["select"]["steps"])
    assert not any("lint-imports" in s.get("run", "") for s in jobs["python-shard"]["steps"])


def test_the_shard_matrix_is_the_selections_and_a_shard_runs_the_targets_it_was_given():
    job = _ci()["python-shard"]
    assert job["needs"] == "select"
    # An empty matrix is an error, so no shard job is the job being skipped.
    assert job["if"] == "github.event_name != 'push' && needs.select.outputs.PYTEST_SHARDS != '[]'"
    assert job["strategy"]["matrix"] == {"shard": "${{ fromJSON(needs.select.outputs.PYTEST_SHARDS) }}"}
    assert job["env"]["SHARD_COUNT"] == "${{ strategy.job-total }}"
    assert job["env"]["PYTEST_TARGETS"] == "${{ needs.select.outputs.PYTEST_TARGETS }}"
    assert not any("select_tests" in s.get("run", "") for s in job["steps"])
    pytest_step = next(s for s in job["steps"] if "pytest $PYTEST_TARGETS" in s.get("run", ""))
    assert "if" not in pytest_step


def test_an_adapter_no_test_names_is_not_selected_through_the_loader_even_though_the_type_table_lists_it(repo):
    assert select(repo, ["starpulse/_internal/runs/dagu.py"]) == Selection([])


def test_a_module_a_conftest_fixture_uses_selects_the_tests_that_request_the_fixture(repo):
    (repo / "starpulse/tests/conftest.py").write_text(
        "import pytest\nfrom starpulse.lone import Y\n\n\n@pytest.fixture\ndef answer():\n    return Y\n"
    )
    (repo / "starpulse/tests/unit/feed/test_leaf.py").write_text("def test_it(answer):\n    assert answer\n")
    assert select(repo, ["starpulse/lone.py"]) == Selection(
        ["starpulse/tests/unit/feed/test_leaf.py", "starpulse/tests/unit/feed/test_lone.py"]
    )


def test_a_module_conftest_code_uses_outside_a_fixture_selects_every_test_the_conftest_serves(repo):
    (repo / "starpulse/tests/conftest.py").write_text("from starpulse.lone import Y\n\nTABLES = (Y,)\n")
    assert select(repo, ["starpulse/lone.py"]) == Selection(
        sorted(str(p.relative_to(repo)) for p in (repo / "starpulse/tests").rglob("test_*.py"))
    )


@pytest.mark.parametrize(
    ("schema", "readers"),
    [
        (
            "starpulse/api.schema.json",
            ["starpulse/contracts/api/schema.py", "starpulse/contracts/api/__main__.py"],
        ),
        (
            "starpulse/schemas/board.schema.json",
            ["starpulse/contracts/adapters.py", "starpulse/contracts/__main__.py"],
        ),
        (
            "starpulse/machine.schema.json",
            ["starpulse/_internal/machines/machine_definition.py"],
        ),
    ],
)
def test_a_schema_selects_the_tests_of_its_readers_not_the_full_suite(repo, schema, readers):
    selected = select(repo, [schema]).tests
    assert selected
    assert len(selected) < len(select(repo, ["starpulse/__init__.py"]).tests)
    assert select(repo, readers).tests == selected


def mapped(**tests: list[str]) -> dict:
    """A coverage map (`ci/coverage_map.py`) of test file -> the source files its tests execute."""
    return {
        "sha": "a" * 40,
        "collected": len(tests),
        "tests": {f"{test}::test_it": files for test, files in tests.items()},
    }


LEAF = "starpulse/leaf.py"
TEST_LEAF = "starpulse/tests/unit/feed/test_leaf.py"
TEST_HUB = "starpulse/tests/unit/hub/test_hub.py"


def test_a_changed_file_in_the_coverage_map_selects_only_the_tests_that_ran_it(repo):
    coverage = mapped(**{TEST_LEAF: [LEAF], TEST_HUB: ["starpulse/_internal/hub/hub.py"]})
    assert select(repo, [LEAF], coverage) == Selection([TEST_LEAF])


def test_a_file_missing_from_the_coverage_map_falls_back_to_the_import_graph(repo):
    coverage = mapped(**{TEST_HUB: ["starpulse/_internal/hub/hub.py"]})
    assert select(repo, [LEAF], coverage) == select(repo, [LEAF])


def test_a_new_test_file_the_map_never_saw_selects_itself(repo):
    new = "starpulse/tests/unit/feed/test_new.py"
    (repo / new).write_text("from starpulse.leaf import X\n")
    assert select(repo, [new], mapped(**{TEST_LEAF: [LEAF]})) == Selection([new])


def test_a_mapped_conftest_selects_its_tests_instead_of_the_full_suite(repo):
    conftest = "starpulse/tests/conftest.py"
    assert select(repo, [conftest], mapped(**{TEST_LEAF: [LEAF, conftest]})) == Selection([TEST_LEAF])
    assert select(repo, [conftest], mapped(**{TEST_LEAF: [LEAF]})) == FULL


def test_a_coverage_map_test_that_no_longer_exists_is_not_selected(repo):
    coverage = mapped(**{TEST_LEAF: [LEAF], "starpulse/tests/unit/gone/test_gone.py": [LEAF]})
    assert select(repo, [LEAF], coverage) == Selection([TEST_LEAF])


def test_main_selects_by_the_newest_published_map(monkeypatch, capsys, repo, tmp_path):
    monkeypatch.chdir(repo)
    maps = tmp_path / "maps"
    publish(mapped(**{TEST_LEAF: [LEAF]}), maps)
    monkeypatch.setattr("select_tests.DEFAULT_DIR", maps)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{LEAF}\n"))
    main([])
    assert f"PYTEST_TARGETS={TEST_LEAF}\n" in capsys.readouterr().out


PYPROJECT = '[project]\nname = "starpulse"\n\n[tool.importlinter]\nroot_package = "starpulse"\n'


def test_a_pyproject_edit_to_the_import_contracts_alone_selects_the_tests_that_read_them(repo):
    (repo / "pyproject.toml").write_text(
        PYPROJECT.replace("root_package", "include_external_packages = true\nroot_package")
    )
    assert select(repo, ["pyproject.toml"], pyproject_before=PYPROJECT) == Selection(["ci/test_avoid_list.py"])


def test_a_pyproject_edit_outside_the_import_contracts_runs_the_full_suite(repo):
    (repo / "pyproject.toml").write_text(PYPROJECT.replace('starpulse"\n', 'starpulse2"\n', 1))
    assert select(repo, ["pyproject.toml"], pyproject_before=PYPROJECT) == FULL


def test_a_pyproject_with_no_earlier_version_to_compare_runs_the_full_suite(repo):
    (repo / "pyproject.toml").write_text(PYPROJECT)
    assert select(repo, ["pyproject.toml"]) == FULL


def test_a_non_python_file_selects_a_mapped_reader_by_the_map_not_the_import_graph(repo):
    reader = "starpulse/_internal/pulls/github.py"
    ran = "starpulse/tests/unit/machines/test_github_pull_request_machine.py"
    coverage = mapped(**{ran: [reader]})
    assert select(repo, ["starpulse/machines/copilot.yaml"], coverage) == Selection([ran])


def test_main_compares_pyproject_with_the_base_it_is_given(monkeypatch, capsys, repo, tmp_path):
    monkeypatch.chdir(repo)
    monkeypatch.setattr("select_tests.DEFAULT_DIR", tmp_path / "no-maps")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    (repo / "pyproject.toml").write_text(PYPROJECT)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "pyproject.toml").write_text(PYPROJECT + '[[tool.importlinter.contracts]]\nname = "c"\n')
    monkeypatch.setattr("sys.stdin", io.StringIO("pyproject.toml\n"))
    main(["--base", base])
    assert "PYTEST_TARGETS=ci/test_avoid_list.py\n" in capsys.readouterr().out


def test_a_change_to_the_board_seam_selects_the_lane_written_test(repo, tmp_path):
    """A change to the board seam's Written (gaining lane and at) selects the test that proves a native write then its
    watch placement yields one history row and one board:lanes entry carrying the request's actor."""
    from select_tests import select

    (repo / "starpulse/_internal/board/seam.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Written:\n"
        "    ok: bool\n"
        "    lane: str | None = None\n"
        "    at: float | None = None\n"
    )
    written_test = repo / "starpulse/tests/unit/server/test_lane_written.py"
    written_test.parent.mkdir(parents=True)
    written_test.write_text("from starpulse._internal.board.seam import Written\n")
    coverage = {
        "tests": {
            "starpulse/tests/unit/server/test_lane_written.py::test_a_write_then_its_placement": [
                "starpulse/_internal/board/seam.py"
            ]
        }
    }
    selection = select(repo, ["starpulse/_internal/board/seam.py"], coverage)

    assert "starpulse/tests/unit/server/test_lane_written.py" in selection.tests
