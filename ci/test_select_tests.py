"""Which tests a pull request runs: those whose imports reach what it changed, the full suite when that is unknowable."""

from __future__ import annotations

import io
import json
from functools import cache
from pathlib import Path

import pytest
import yaml
from select_tests import FULL, SHARD_COUNT, Selection, main, select, shards_for

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
ROOT = Path(__file__).resolve().parents[1]


@cache
def _every_test_the_package_reaches() -> int:
    """How many test files a change to the package's own `__init__.py` selects, read once for the real repository."""
    return len(select(ROOT, ["starpulse/__init__.py"]).tests)


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
        "ci/sizer.py": "",
        "ci/test_sizer.py": "from sizer import X\n",
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
        "starpulse/machines/copilot.yaml",
        "starpulse/skills/writing-starpulse-adapters/SKILL.md",
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
                "ci/test_load.py",
                "ci/test_page_latency.py",
                "ci/test_sizer.py",
                "ci/test_soak.py",
                "ci/test_ui_preview.py",
            ],
        ),
        ("bench/page_latency.py", ["ci/test_load.py", "ci/test_page_latency.py", "ci/test_soak.py"]),
        ("bench/soak.py", ["ci/test_soak.py"]),
        ("bench/load.py", ["ci/test_load.py"]),
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
        "plugins/starpulse-board/hooks/draw.ts",
        "plugins/starpulse-board/hooks/hooks.json",
    ],
)
def test_a_file_no_test_reads_selects_nothing(repo, path):
    assert select(repo, [path]) == Selection([])


def test_a_non_python_file_whose_mapped_reader_is_gone_runs_the_full_suite(repo):
    (repo / "starpulse/_internal/server/server.py").unlink()
    assert select(repo, ["README.md"]) == FULL


def test_the_real_repository_selects_a_subset_for_one_adapter():
    root = Path(__file__).resolve().parents[1]
    selected = select(root, ["starpulse/_internal/board/jira.py"]).tests
    assert "starpulse/tests/integration/board/test_jira.py" in selected
    assert "ci/test_workflow_placement.py" not in selected


def test_a_diff_touching_a_python_source_file_selects_a_target_and_so_launches_a_shard():
    """The blind spot of sizing the matrix from the selection: a selector that finds nothing turns a real change green."""
    for changed in ("ci/shard.py", "starpulse/__init__.py"):
        selection = select(ROOT, [changed])
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


def _printed(monkeypatch, capsys, stdin: str, *args: str) -> dict[str, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    main(list(args))
    return dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())


def test_a_diff_selecting_no_test_prints_no_target_and_no_shard(monkeypatch, capsys):
    printed = _printed(monkeypatch, capsys, "CONTRIBUTING.md\n")
    assert printed["PYTEST_TARGETS"] == ""
    assert json.loads(printed["PYTEST_SHARDS"]) == []


def test_a_diff_selecting_a_test_prints_its_target_and_the_shards_it_needs(monkeypatch, capsys):
    printed = _printed(monkeypatch, capsys, "ci/shard.py\n")
    assert "ci/test_shard.py" in printed["PYTEST_TARGETS"].split()
    assert json.loads(printed["PYTEST_SHARDS"])


def test_a_diff_that_runs_the_full_suite_prints_no_target_and_every_shard(monkeypatch, capsys):
    printed = _printed(monkeypatch, capsys, "pyproject.toml\n")
    assert printed["PYTEST_TARGETS"] == ""
    assert json.loads(printed["PYTEST_SHARDS"]) == [1, 2, 3, 4, 5, 6]


def test_full_prints_every_shard_whatever_the_diff(monkeypatch, capsys):
    """The nightly schedule and a manual dispatch have no diff: they read none and run everything."""
    printed = _printed(monkeypatch, capsys, "", "--full")
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
            ["starpulse/contracts/api.py", "starpulse/contracts/__main__.py"],
        ),
        (
            "starpulse/schemas/board.schema.json",
            ["starpulse/contracts/adapters.py", "starpulse/contracts/__main__.py"],
        ),
        (
            "starpulse/machine.schema.json",
            ["starpulse/_internal/machines/machine_definition.py", "starpulse/_internal/config/triggers.py"],
        ),
    ],
)
# Stays slow: the first case on each worker parses the import graph of every module in the repository, which is the
# selection under test; later cases reuse the cached parse.
def test_a_schema_selects_the_tests_of_its_readers_not_the_full_suite(schema, readers):
    selected = select(ROOT, [schema]).tests
    assert selected
    assert len(selected) < _every_test_the_package_reaches()
    assert select(ROOT, readers).tests == selected
