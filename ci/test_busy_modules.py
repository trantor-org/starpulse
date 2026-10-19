"""`ci/busy_modules.py` fails a tracked production module over trantor's busy-module limit with no live split-pending entry.

Runs trantor's limit and lists (its `lib/`, from `TRANTOR_LIB`, the static-checks job's `.trantor/lib` or the trantor
checkout this tree is a submodule of) over a scratch git repository, so it is skipped where none of those is present.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import busy_modules

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [Path(os.environ.get("TRANTOR_LIB", "/nonexistent")), ROOT / ".trantor/lib"]
CANDIDATES += [parent / "lib" for parent in ROOT.parents]
TRANTOR_LIB = next((lib for lib in CANDIDATES if (lib / "linting/check_config_checks/busy_modules.py").is_file()), None)

pytestmark = pytest.mark.skipif(TRANTOR_LIB is None, reason="trantor's lib/ is not checked out")


def repo(tmp_path: Path, files: dict[str, int]) -> Path:
    """A git repository tracking each of *files* with the given number of lines."""
    for rel, lines in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n" * lines)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def test_a_production_module_over_the_limit_fails_naming_it_and_its_size(tmp_path):
    root = repo(tmp_path, {"starpulse/_internal/big.py": 1501, "starpulse/web/src/ok.ts": 1500})
    assert busy_modules.violations(TRANTOR_LIB, root, "2026-10-18") == [
        "starpulse/_internal/big.py is 1501 lines, over 1500: split it by responsibility "
        "(docs/governance/repository-layout/packages-and-tests.md, A Busy Module Stays Under 1,500 Lines)"
    ]


def test_modules_under_the_limit_tests_generated_and_untracked_files_pass(tmp_path):
    root = repo(
        tmp_path,
        {
            "starpulse/_internal/ok.py": 1500,
            "starpulse/tests/unit/test_big.py": 1600,
            "starpulse/web/src/api/types.gen.ts": 1600,
            "ci/big.py": 1600,
        },
    )
    (root / "starpulse/untracked.py").write_text("x = 1\n" * 1600)
    assert busy_modules.violations(TRANTOR_LIB, root, "2026-10-18") == []


def test_a_split_pending_entry_excuses_its_module_until_its_date(tmp_path, monkeypatch):
    root = repo(tmp_path, {"starpulse/big.py": 1501})
    busy_modules.violations(TRANTOR_LIB, root, "2026-10-18")  # loads trantor's module
    pending = sys.modules["linting.check_config_checks.busy_modules"].SPLIT_PENDING
    monkeypatch.setitem(pending, "starpulse/starpulse/big.py", ("2026-10-18", "TASK-1"))
    assert busy_modules.violations(TRANTOR_LIB, root, "2026-10-18") == []
    assert len(busy_modules.violations(TRANTOR_LIB, root, "2026-10-19")) == 1
