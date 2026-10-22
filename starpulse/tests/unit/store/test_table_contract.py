"""A writer that bypasses the store: `lint-imports` refuses any module outside the store package that imports its tables."""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

_CONTRACT = "store-table-private"
_PYPROJECT = Path(__file__).parents[4] / "pyproject.toml"


def _contract() -> dict[str, Any]:
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    found = [contract for contract in contracts if contract["id"] == _CONTRACT]
    assert found, f"pyproject.toml declares no {_CONTRACT} import contract"
    return found[0]


def _lint(root: Path, outsider: str) -> subprocess.CompletedProcess[str]:
    """Lint a `fixture` package shaped like starpulse's, under the real contract with its module names retargeted."""
    package = root / "fixture" / "_internal"
    (package / "store").mkdir(parents=True)
    for init in (root / "fixture", package, package / "store"):
        (init / "__init__.py").write_text("")
    (package / "store" / "tables.py").write_text("stream_events = object()\n")
    (package / "store" / "event_store.py").write_text("from fixture._internal.store.tables import stream_events\n")
    (package / "other.py").write_text(outsider)
    contract = json.loads(json.dumps(_contract()).replace("starpulse", "fixture"))
    config = root / "contract.toml"
    config.write_text(
        '[tool.importlinter]\nroot_package = "fixture"\n[[tool.importlinter.contracts]]\n'
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in contract.items())
        + "\n"
    )
    lint_imports = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    return subprocess.run([lint_imports, "--config", str(config)], cwd=root, capture_output=True, text=True, check=False)


def test_a_module_outside_the_store_importing_its_tables_breaks_the_contract(tmp_path: Path) -> None:
    result = _lint(tmp_path, "from fixture._internal.store.tables import stream_events\n")

    assert result.returncode != 0
    assert "fixture._internal.other" in result.stdout


@pytest.mark.parametrize("outsider", ["from fixture._internal.store import event_store\n", "x = 1\n"])
def test_the_store_package_and_modules_that_use_it_keep_the_contract(tmp_path: Path, outsider: str) -> None:
    result = _lint(tmp_path, outsider)

    assert result.returncode == 0, result.stdout
