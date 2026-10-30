"""Which tests a pull request runs: those whose imports reach what it changed, the full suite when that is unknowable."""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from coverage_map import publish
from select_tests import FULL, READERS, Selection, main, select

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A package with a leaf module, an event log that imports it, an adapter loaded by name, and one test per module."""
    files = {
        "starpulse/__init__.py": "",
        "starpulse/leaf.py": "X = 1\n",
        "starpulse/lone.py": "Y = 2\n",
        "starpulse/board/model/seam.py": "import importlib\nfrom starpulse.board.model.adapter_types import module_name\n",
        "starpulse/runs/adapters/outbound/dagu.py": "def start(): ...\ndef follow(): ...\n",
        "starpulse/board/model/adapter_types.py": 'BUILT_IN = {"dagu": "starpulse.runs.adapters.outbound.dagu", "jira": "x"}\n',
        "starpulse/event_log/__init__.py": "",
        "starpulse/runtime/server.py": "",
        "starpulse/event_log/event_log.py": "from starpulse import leaf\n",
        "starpulse/event_log/migrations/versions/0001_initial.py": "",
        "starpulse/board/adapters/jira.py": "def board(settings, base):\n    return None\n",
        "tests/__init__.py": "",
        "tests/conftest.py": "",
        "tests/helpers.py": "from starpulse import lone\n",
        "tests/unit/feed/test_leaf.py": "from starpulse.leaf import X\n",
        "tests/unit/event_log/test_event_log.py": "from starpulse.event_log import event_log\n",
        "tests/unit/feed/test_lone.py": "from tests.helpers import lone\n",
        "tests/unit/board/test_board.py": 'from starpulse.board.model import seam\n\nKIND = "jira"\n',
        "tests/unit/contracts/test_public_surface.py": "import starpulse\n",
        "tests/unit/contracts/test_neutrality.py": "import starpulse\n",
        "tests/unit/event_log/test_consumer_pattern.py": "import starpulse\n",
        "tests/unit/board/test_builtin_types.py": "import starpulse\n",
        "starpulse/runtime/config_reference.py": "",
        "tests/unit/runtime/test_config_model.py": "from starpulse.runtime import config_reference\n",
        "starpulse/contracts/__init__.py": "",
        "starpulse/contracts/api/__init__.py": "",
        "starpulse/contracts/api/schema.py": "",
        "starpulse/contracts/api/__main__.py": "",
        "starpulse/contracts/__main__.py": "",
        "starpulse/contracts/adapters.py": "",
        "starpulse/machine_engine/adapters/machine_loader.py": "",
        "tests/unit/contracts/test_contracts.py": "from starpulse.contracts import adapters\nfrom starpulse.contracts.api import schema\n",
        "tests/unit/machine_engine/test_machine_definition.py": "from starpulse.machine_engine.adapters import machine_loader\n",
        "starpulse/pulls/model/ci.py": "",
        "starpulse/harness_telemetry/model/harness.py": "",
        "starpulse/pulls/adapters/outbound/github.py": "",
        "starpulse/cli/skill_install.py": "",
        "tests/unit/pulls/test_github.py": "from starpulse.pulls.adapters.outbound import github\n",
        "tests/unit/machine_engine/test_github_pull_request_machine.py": "import starpulse\n",
        "tests/integration/cli/test_agent_cli.py": "from starpulse.cli import skill_install\n",
        "ci/sizer.py": "",
        "ci/test_sizer.py": "from sizer import X\n",
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
        ["tests/unit/event_log/test_event_log.py", "tests/unit/feed/test_leaf.py"]
    )


def test_a_changed_test_helper_selects_the_tests_that_import_it(repo):
    assert select(repo, ["tests/helpers.py"]) == Selection(["tests/unit/feed/test_lone.py"])


def test_a_changed_test_file_selects_itself(repo):
    assert select(repo, ["tests/unit/feed/test_lone.py"]) == Selection(["tests/unit/feed/test_lone.py"])


CONTRACT_TEST = "tests/unit/contracts/test_raw_task_feed_row.py"
CONTRACT_PRODUCERS = [
    "starpulse/board/feed/views.py",
    "starpulse/board/feed/reads.py",
    "starpulse/board/feed/shared.py",
    "starpulse/contracts/api/dto/task.py",
    "starpulse/contracts/api/dto/machine.py",
]


@pytest.mark.parametrize("changed", CONTRACT_PRODUCERS)
def test_a_feed_or_dto_change_selects_the_raw_task_contract_test_by_import_graph_and_by_map(changed):
    other = "tests/unit/views/test_other.py"
    assert CONTRACT_TEST in select(ROOT, [changed]).tests
    assert CONTRACT_TEST in select(ROOT, [changed], mapped(**{other: [changed]})).tests


def test_a_ci_script_selects_the_ci_test_that_imports_it_by_its_bare_name(repo):
    assert select(repo, ["ci/sizer.py"]) == Selection(["ci/test_sizer.py"])


def test_an_adapter_selects_the_tests_of_the_loader_that_imports_it_by_name(repo):
    assert "tests/unit/board/test_board.py" in select(repo, ["starpulse/board/adapters/jira.py"]).tests


def test_named_loaders_expand_when_the_last_module_popped_is_covered_only_by_other_tests(repo):
    """The loader is the last module a test reaches and another test alone covers it: its adapter still counts."""
    coverage = {"tests": {"tests/unit/other/test_seam.py::test_seam": ["starpulse/board/model/seam.py"]}}
    assert "tests/unit/board/test_board.py" in select(repo, ["starpulse/board/adapters/jira.py"], coverage).tests


def test_a_package_init_selects_every_test_under_the_package(repo):
    assert select(repo, ["starpulse/__init__.py"]) == Selection(
        sorted(str(p.relative_to(repo)) for p in (repo / "tests").rglob("test_*.py"))
    )


def test_a_migration_selects_the_tests_of_the_module_that_runs_migrations(repo):
    assert select(repo, ["starpulse/event_log/migrations/versions/0001_initial.py"]) == Selection(
        ["tests/unit/event_log/test_event_log.py"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "tests/conftest.py",
        "tests/fixtures/jira/search_page_1.json",
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
        ("docs/public-surface.md", ["tests/unit/contracts/test_public_surface.py"]),
        ("starpulse/web/src/App.tsx", ["ci/test_ui_preview.py", "tests/unit/contracts/test_neutrality.py"]),
        ("docs/consumers.md", ["tests/unit/event_log/test_consumer_pattern.py"]),
        ("docs/serving.md", ["tests/unit/board/test_builtin_types.py", "tests/unit/runtime/test_config_model.py"]),
        ("docs/sources.md", ["tests/unit/board/test_builtin_types.py"]),
        (
            ".github/workflows/ci.yml",
            [
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
                "tests/unit/machine_engine/test_github_pull_request_machine.py",
                "tests/unit/pulls/test_github.py",
            ],
        ),
        (
            "starpulse/skills/writing-starpulse-adapters/SKILL.md",
            ["tests/integration/cli/test_agent_cli.py"],
        ),
        ("ci/static_checks.sh", ["ci/test_workflow_placement.py"]),
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
        "bench/free_threading/run.sh",
    ],
)
def test_a_file_no_test_reads_selects_nothing(repo, path):
    assert select(repo, [path]) == Selection([])


def test_a_non_python_file_whose_mapped_reader_is_gone_runs_the_full_suite(repo):
    (repo / "starpulse/runtime/server.py").unlink()
    assert select(repo, ["README.md"]) == FULL


def test_a_deleted_test_file_selects_nothing(repo):
    assert select(repo, ["tests/unit/feed/test_gone.py"]) == Selection([])


def test_a_module_replaced_by_a_package_selects_the_tests_that_import_the_package(repo):
    """`contracts/api.py` became `contracts/api/__init__.py`: its importers still import the name."""
    assert select(repo, ["starpulse/contracts/api.py"]) == Selection(["tests/unit/contracts/test_contracts.py"])


def test_an_adapter_selects_a_subset_and_not_the_ci_tests(repo):
    selected = select(repo, ["starpulse/board/adapters/jira.py"]).tests
    assert "tests/unit/board/test_board.py" in selected
    assert "ci/test_sizer.py" not in selected


def test_every_file_the_readers_map_names_exists_in_the_real_repository():
    """The one check the fixture repository cannot make: a stale entry sends `select` to the full suite for its file."""
    missing = [reader for readers in READERS.values() for reader in readers if not (ROOT / reader).is_file()]
    assert not missing


def test_a_diff_touching_a_python_source_file_selects_a_target(repo):
    """The blind spot of skipping the python step on an empty selection: a selector that finds nothing turns a real change green."""
    for changed in ("ci/sizer.py", "starpulse/__init__.py"):
        selection = select(repo, [changed])
        assert selection.tests


def _printed(monkeypatch, capsys, repo, stdin: str, *args: str) -> dict[str, str]:
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    main(list(args))
    return dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())


def test_a_diff_selecting_no_test_prints_no_target_and_no_python_step(monkeypatch, capsys, repo):
    printed = _printed(monkeypatch, capsys, repo, "CONTRIBUTING.md\n")
    assert printed["PYTEST_TARGETS"] == ""
    assert printed["python"] == "false"


def test_a_diff_selecting_a_test_prints_its_target_and_runs_the_python_step(monkeypatch, capsys, repo):
    printed = _printed(monkeypatch, capsys, repo, "ci/sizer.py\n")
    assert "ci/test_sizer.py" in printed["PYTEST_TARGETS"].split()
    assert printed["python"] == "true"


def test_a_diff_that_runs_the_full_suite_prints_no_target_and_runs_the_python_step(monkeypatch, capsys, repo):
    printed = _printed(monkeypatch, capsys, repo, "pyproject.toml\n")
    assert printed["PYTEST_TARGETS"] == ""
    assert printed["python"] == "true"


def test_full_runs_the_python_step_whatever_the_diff(monkeypatch, capsys, repo):
    """The nightly schedule and a manual dispatch have no diff: they read none and run everything."""
    printed = _printed(monkeypatch, capsys, repo, "", "--full")
    assert printed["PYTEST_TARGETS"] == ""
    assert printed["python"] == "true"


def _ci() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]


def _function(name: str) -> str:
    """The body of a function in ci/run.sh, the CI entry point the jobs call."""
    script = (CI.parents[2] / "ci/run.sh").read_text()
    return re.search(rf"^{name}\(\) \{{\n(.*?)^\}}$", script, re.DOTALL | re.MULTILINE).group(1)


def test_without_a_base_select_chooses_everything_and_a_base_narrows_it():
    """The nightly DAG and a dispatch have no base commit, so both select everything; the sp-ci DAG sets BASE for a pull request."""
    script = _function("cmd_select")
    assert "python ci/select_tests.py --full" in script
    assert '--base "$BASE"' in script


def test_select_runs_in_a_bare_environment_without_syncing_the_project():
    """Its scripts import only the standard library, so a locked sync is seconds on the merge queue's critical path."""
    assert "uv sync" not in _function("cmd_select")


def test_the_import_layers_are_checked_in_the_static_checks_not_in_select_or_the_python_tests():
    assert "lint-imports" not in _function("cmd_select")
    assert "lint-imports" in (ROOT / "ci/static_checks.sh").read_text()
    assert "lint-imports" not in _function("cmd_python_tests")


def test_the_python_tests_run_the_targets_they_were_given():
    assert "pytest ${PYTEST_TARGETS:-}" in _function("cmd_python_tests")


def test_an_adapter_no_test_names_is_not_selected_through_the_loader_even_though_the_type_table_lists_it(repo):
    assert select(repo, ["starpulse/runs/adapters/outbound/dagu.py"]) == Selection([])


def test_a_module_a_conftest_fixture_uses_selects_the_tests_that_request_the_fixture(repo):
    (repo / "tests/conftest.py").write_text(
        "import pytest\nfrom starpulse.lone import Y\n\n\n@pytest.fixture\ndef answer():\n    return Y\n"
    )
    (repo / "tests/unit/feed/test_leaf.py").write_text("def test_it(answer):\n    assert answer\n")
    assert select(repo, ["starpulse/lone.py"]) == Selection(
        ["tests/unit/feed/test_leaf.py", "tests/unit/feed/test_lone.py"]
    )


def test_a_module_conftest_code_uses_outside_a_fixture_selects_every_test_the_conftest_serves(repo):
    (repo / "tests/conftest.py").write_text("from starpulse.lone import Y\n\nTABLES = (Y,)\n")
    assert select(repo, ["starpulse/lone.py"]) == Selection(
        sorted(str(p.relative_to(repo)) for p in (repo / "tests").rglob("test_*.py"))
    )


@pytest.mark.parametrize(
    ("schema", "readers"),
    [
        (
            "starpulse/schemas/api.schema.json",
            ["starpulse/contracts/api/schema.py", "starpulse/contracts/api/__main__.py"],
        ),
        (
            "starpulse/schemas/board.schema.json",
            ["starpulse/contracts/adapters.py", "starpulse/contracts/__main__.py"],
        ),
        (
            "starpulse/schemas/machine.schema.json",
            ["starpulse/machine_engine/adapters/machine_loader.py"],
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
TEST_LEAF = "tests/unit/feed/test_leaf.py"
TEST_LOG = "tests/unit/event_log/test_event_log.py"


def test_a_changed_file_in_the_coverage_map_selects_only_the_tests_that_ran_it(repo):
    coverage = mapped(**{TEST_LEAF: [LEAF], TEST_LOG: ["starpulse/event_log/event_log.py"]})
    assert select(repo, [LEAF], coverage) == Selection([TEST_LEAF])


def test_a_file_missing_from_the_coverage_map_falls_back_to_the_import_graph(repo):
    coverage = mapped(**{TEST_LOG: ["starpulse/event_log/event_log.py"]})
    assert select(repo, [LEAF], coverage) == select(repo, [LEAF])


def test_a_new_test_file_the_map_never_saw_selects_itself(repo):
    new = "tests/unit/feed/test_new.py"
    (repo / new).write_text("from starpulse.leaf import X\n")
    assert select(repo, [new], mapped(**{TEST_LEAF: [LEAF]})) == Selection([new])


def test_a_mapped_conftest_selects_its_tests_instead_of_the_full_suite(repo):
    conftest = "tests/conftest.py"
    assert select(repo, [conftest], mapped(**{TEST_LEAF: [LEAF, conftest]})) == Selection([TEST_LEAF])
    assert select(repo, [conftest], mapped(**{TEST_LEAF: [LEAF]})) == FULL


def test_a_coverage_map_test_that_no_longer_exists_is_not_selected(repo):
    coverage = mapped(**{TEST_LEAF: [LEAF], "tests/unit/gone/test_gone.py": [LEAF]})
    assert select(repo, [LEAF], coverage) == Selection([TEST_LEAF])


def _commit(root: Path, message: str) -> str:
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", message], check=True)
    return subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def test_a_module_moved_since_the_maps_sha_keeps_the_tests_the_map_recorded_for_its_old_path(repo):
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    built_at = _commit(repo, "map built")
    moved = "starpulse/event_log/leaf.py"
    subprocess.run(["git", "-C", str(repo), "mv", LEAF, moved], check=True)
    _commit(repo, "move leaf")
    coverage = mapped(**{TEST_LEAF: [LEAF]}) | {"sha": built_at}
    assert select(repo, [moved], coverage) == Selection([TEST_LEAF])


def test_main_selects_by_the_newest_published_map(monkeypatch, capsys, repo, tmp_path):
    monkeypatch.chdir(repo)
    maps = tmp_path / "maps"
    publish(mapped(**{TEST_LEAF: [LEAF]}), maps)
    monkeypatch.setattr("select_tests.DEFAULT_DIR", maps)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{LEAF}\n"))
    main([])
    assert f"PYTEST_TARGETS={TEST_LEAF}\n" in capsys.readouterr().out


PYPROJECT = '[project]\nname = "starpulse"\n\n[tool.importlinter]\nroot_package = "starpulse"\n'


def test_a_pyproject_edit_to_the_import_contracts_alone_selects_no_test(repo):
    (repo / "pyproject.toml").write_text(
        PYPROJECT.replace("root_package", "include_external_packages = true\nroot_package")
    )
    assert select(repo, ["pyproject.toml"], pyproject_before=PYPROJECT) == Selection([])


def test_a_pyproject_edit_outside_the_import_contracts_runs_the_full_suite(repo):
    (repo / "pyproject.toml").write_text(PYPROJECT.replace('starpulse"\n', 'starpulse2"\n', 1))
    assert select(repo, ["pyproject.toml"], pyproject_before=PYPROJECT) == FULL


def test_a_pyproject_with_no_earlier_version_to_compare_runs_the_full_suite(repo):
    (repo / "pyproject.toml").write_text(PYPROJECT)
    assert select(repo, ["pyproject.toml"]) == FULL


def test_a_non_python_file_selects_a_mapped_reader_by_the_map_not_the_import_graph(repo):
    reader = "starpulse/pulls/adapters/outbound/github.py"
    ran = "tests/unit/machine_engine/test_github_pull_request_machine.py"
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
    assert "PYTEST_TARGETS=\n" in capsys.readouterr().out


def test_a_change_to_the_board_seam_selects_the_lane_written_test(repo, tmp_path):
    """A change to the board seam's Written (gaining lane and at) selects the test that proves a native write then its
    watch placement yields one history row and one board:lanes entry carrying the request's actor."""
    from select_tests import select

    (repo / "starpulse/board/model/seam.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Written:\n"
        "    ok: bool\n"
        "    lane: str | None = None\n"
        "    at: float | None = None\n"
    )
    written_test = repo / "tests/unit/server/test_lane_written.py"
    written_test.parent.mkdir(parents=True)
    written_test.write_text("from starpulse.board.model.seam import Written\n")
    coverage = {
        "tests": {
            "tests/unit/server/test_lane_written.py::test_a_write_then_its_placement": ["starpulse/board/model/seam.py"]
        }
    }
    selection = select(repo, ["starpulse/board/model/seam.py"], coverage)

    assert "tests/unit/server/test_lane_written.py" in selection.tests


def test_a_change_to_the_github_package_reaches_the_pulls_tests(repo: Path) -> None:
    from select_tests import select

    (repo / "starpulse/github").mkdir(parents=True)
    (repo / "starpulse/github/__init__.py").write_text("def connect(): ...\n")
    pulls_test = repo / "tests/integration/pulls/test_github.py"
    pulls_test.parent.mkdir(parents=True)
    pulls_test.write_text("from starpulse.github import connect\n")
    coverage = {
        "tests": {"tests/integration/pulls/test_github.py::test_connect_reads_a_page": ["starpulse/github/__init__.py"]}
    }
    selection = select(repo, ["starpulse/github/__init__.py"], coverage)

    assert "tests/integration/pulls/test_github.py" in selection.tests


def test_a_selection_reports_the_coverage_maps_sha_age_and_lost_files(monkeypatch, capsys, repo, tmp_path):
    maps = tmp_path / "maps"
    publish({"sha": "abc", "collected": 1, "tests": {TEST_LEAF: [LEAF, "starpulse/gone/moved.py"]}}, maps)
    monkeypatch.setattr("select_tests.DEFAULT_DIR", maps)

    printed = _printed(monkeypatch, capsys, repo, f"{LEAF}\n")

    assert printed["COVERAGE_MAP_SHA"] == "abc"
    assert float(printed["COVERAGE_MAP_AGE_HOURS"]) < 1
    assert (printed["COVERAGE_MAP_FILES"], printed["COVERAGE_MAP_MISSING"]) == ("2", "1")


def test_a_selection_without_a_coverage_map_reports_an_empty_sha(monkeypatch, capsys, repo, tmp_path):
    monkeypatch.setattr("select_tests.DEFAULT_DIR", tmp_path / "no-maps")

    printed = _printed(monkeypatch, capsys, repo, f"{LEAF}\n")

    assert printed["COVERAGE_MAP_SHA"] == ""
