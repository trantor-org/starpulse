"""Which tests a pull request runs: those whose imports reach what it changed, the full suite when that is unknowable."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from select_tests import FULL, Selection, select

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A package with a leaf module, a hub that imports it, an adapter loaded by name, and one test per module."""
    files = {
        "starpulse/__init__.py": "",
        "starpulse/leaf.py": "X = 1\n",
        "starpulse/lone.py": "Y = 2\n",
        "starpulse/board.py": "import importlib\n",
        "starpulse/dagu.py": "def start(): ...\ndef follow(): ...\n",
        "starpulse/server.py": "",
        "starpulse/hub.py": "from starpulse import leaf\n",
        "starpulse/migrations/versions/0001_initial.py": "",
        "starpulse/jira.py": "def board(settings, base):\n    return None\n",
        "starpulse/tests/__init__.py": "",
        "starpulse/tests/conftest.py": "",
        "starpulse/tests/helpers.py": "from starpulse import lone\n",
        "starpulse/tests/unit/test_leaf.py": "from starpulse.leaf import X\n",
        "starpulse/tests/unit/test_hub.py": "from starpulse import hub\n",
        "starpulse/tests/unit/test_lone.py": "from starpulse.tests.helpers import lone\n",
        "starpulse/tests/unit/test_board.py": 'from starpulse import board\n\nKIND = "jira"\n',
        "starpulse/tests/unit/test_public_surface.py": "",
        "starpulse/tests/unit/test_neutrality.py": "",
        "ci/sizer.py": "",
        "ci/test_sizer.py": "from sizer import X\n",
        "ci/ui_preview.py": "",
        "ci/test_ui_preview.py": "import ui_preview\n",
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return tmp_path


def test_a_changed_module_selects_the_tests_that_import_it_directly_or_through_another_module(repo):
    assert select(repo, ["starpulse/leaf.py"]) == Selection(
        ["starpulse/tests/unit/test_hub.py", "starpulse/tests/unit/test_leaf.py"]
    )


def test_a_changed_test_helper_selects_the_tests_that_import_it(repo):
    assert select(repo, ["starpulse/tests/helpers.py"]) == Selection(["starpulse/tests/unit/test_lone.py"])


def test_a_changed_test_file_selects_itself(repo):
    assert select(repo, ["starpulse/tests/unit/test_lone.py"]) == Selection(["starpulse/tests/unit/test_lone.py"])


def test_a_ci_script_selects_the_ci_test_that_imports_it_by_its_bare_name(repo):
    assert select(repo, ["ci/sizer.py"]) == Selection(["ci/test_sizer.py"])


def test_an_adapter_selects_the_tests_of_the_loader_that_imports_it_by_name(repo):
    assert "starpulse/tests/unit/test_board.py" in select(repo, ["starpulse/jira.py"]).tests


def test_a_package_init_selects_every_test_under_the_package(repo):
    assert select(repo, ["starpulse/__init__.py"]) == Selection(
        sorted(str(p.relative_to(repo)) for p in (repo / "starpulse/tests").rglob("test_*.py"))
    )


def test_a_migration_selects_the_tests_of_the_module_that_runs_migrations(repo):
    assert select(repo, ["starpulse/migrations/versions/0001_initial.py"]) == Selection(
        ["starpulse/tests/unit/test_hub.py"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "starpulse/tests/conftest.py",
        "starpulse/tests/fixtures/jira/search_page_1.json",
        "starpulse/machines/copilot.yaml",
        "starpulse/schemas/board.schema.json",
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
        ("README.md", ["ci/test_ui_preview.py", "starpulse/tests/unit/test_public_surface.py"]),
        ("starpulse/web/src/App.tsx", ["ci/test_ui_preview.py", "starpulse/tests/unit/test_neutrality.py"]),
        (".github/workflows/ci.yml", ["ci/test_sizer.py", "ci/test_ui_preview.py"]),
    ],
)
def test_a_mapped_non_python_file_selects_the_tests_that_read_it(repo, path, tests):
    assert select(repo, [path]) == Selection(tests)


@pytest.mark.parametrize(
    "path",
    [
        "CONTRIBUTING.md",
        "LICENSE",
        ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/pull_request_template.md",
        "bench/hub_ingest.py",
    ],
)
def test_a_file_no_test_reads_selects_nothing(repo, path):
    assert select(repo, [path]) == Selection([])


def test_a_non_python_file_whose_mapped_reader_is_gone_runs_the_full_suite(repo):
    (repo / "starpulse/server.py").unlink()
    assert select(repo, ["README.md"]) == FULL


def test_the_real_repository_selects_a_subset_for_one_adapter():
    root = Path(__file__).resolve().parents[1]
    selected = select(root, ["starpulse/jira.py"]).tests
    assert "starpulse/tests/unit/test_jira.py" in selected
    assert "ci/test_workflow_placement.py" not in selected


@pytest.mark.parametrize("name", ["python", "ic"])
def test_a_pull_request_runs_the_selection_and_a_push_runs_everything(name):
    job = yaml.safe_load(CI.read_text())["jobs"][name]
    assert "if" not in job  # the job always runs, so its required check reports even when no test is selected
    steps = job["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 2  # the merge commit and its base parent
    select_step = next(s for s in steps if "ci/select_tests.py" in s.get("run", ""))
    assert select_step["if"] == "github.event_name == 'pull_request'"
    pytest_step = next(s for s in steps if s.get("run", "").rstrip().endswith("pytest $PYTEST_TARGETS"))
    assert pytest_step["if"] == "env.PYTEST_SKIP != 'true'"
    assert steps.index(select_step) < steps.index(pytest_step)


def test_an_adapter_no_test_names_is_not_selected_through_the_loader(repo):
    assert select(repo, ["starpulse/dagu.py"]) == Selection([])


def test_a_module_a_conftest_fixture_uses_selects_the_tests_that_request_the_fixture(repo):
    (repo / "starpulse/tests/conftest.py").write_text(
        "import pytest\nfrom starpulse.lone import Y\n\n\n@pytest.fixture\ndef answer():\n    return Y\n"
    )
    (repo / "starpulse/tests/unit/test_leaf.py").write_text("def test_it(answer):\n    assert answer\n")
    assert select(repo, ["starpulse/lone.py"]) == Selection(
        ["starpulse/tests/unit/test_leaf.py", "starpulse/tests/unit/test_lone.py"]
    )


def test_a_module_conftest_code_uses_outside_a_fixture_selects_every_test_the_conftest_serves(repo):
    (repo / "starpulse/tests/conftest.py").write_text("from starpulse.lone import Y\n\nTABLES = (Y,)\n")
    assert select(repo, ["starpulse/lone.py"]) == Selection(
        sorted(str(p.relative_to(repo)) for p in (repo / "starpulse/tests").rglob("test_*.py"))
    )
