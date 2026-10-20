"""`ci/avoid_list.py` fails a change that adds a glossary's avoided term in a context package's new names.

Runs trantor's gate (its `lib/`, from `TRANTOR_LIB`, the static-checks job's `.trantor/lib` or the trantor checkout
this tree is a submodule of) over a scratch git repository, so it is skipped where none of those is present.
"""

import os
import subprocess
from pathlib import Path

import pytest

import avoid_list

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [Path(os.environ.get("TRANTOR_LIB", "/nonexistent")), ROOT / ".trantor/lib"]
CANDIDATES += [parent / "lib" for parent in ROOT.parents]
TRANTOR_LIB = next((lib for lib in CANDIDATES if any((lib / layout / "avoid_list.py").is_file() for layout in ("linting", "linting/linting"))), None)

pytestmark = pytest.mark.skipif(TRANTOR_LIB is None, reason="trantor's lib/ is not checked out")

PYPROJECT = """
[[tool.importlinter.contracts]]
id = "context-runs"
name = "Runs"
type = "forbidden"
source_modules = ["starpulse._internal.runs"]
forbidden_modules = []
"""
GLOSSARY = """# Runs

**Run**:
One execution of a DAG.
_Avoid_: job, execution
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "starpulse/_internal/runs").mkdir(parents=True)
    (root / "starpulse/_internal/board").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "starpulse/_internal/runs/ingest.py").write_text("def old_job():\n    pass\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
    glossaries = tmp_path / "glossaries"
    glossaries.mkdir()
    (glossaries / "runs-ubiquitous-language.md").write_text(GLOSSARY)
    return root


def check(root: Path) -> list[str]:
    return avoid_list.findings(TRANTOR_LIB, root, root.parent / "glossaries", "HEAD")


def test_an_added_avoided_name_in_a_context_package_fails(repo):
    (repo / "starpulse/_internal/runs/ingest.py").write_text("def old_job():\n    pass\n\n\nclass JobQueue:\n    pass\n")

    assert check(repo) == [
        "starpulse/_internal/runs/ingest.py:5: 'job' is on the runs avoid-list; say 'Run'",
    ]


def test_an_unchanged_name_and_a_name_outside_the_context_pass(repo):
    (repo / "starpulse/_internal/board/jobs.py").write_text("def job_count():\n    return 0\n")
    git(repo, "add", ".")

    assert check(repo) == []
