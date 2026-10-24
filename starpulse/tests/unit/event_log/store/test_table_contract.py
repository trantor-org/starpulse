"""A writer that bypasses a table owner: `lint-imports` refuses any module outside the owning package that imports its tables."""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

#: (contract id, owning package, a module of it that uses the tables, a table name)
_OWNERS = [
    ("store-table-private", "store", "event_store", "stream_events"),
    ("readmodel-table-private", "readmodel", "rows", "tasks"),
]
_PYPROJECT = Path(__file__).parents[5] / "pyproject.toml"


def _contract(contract_id: str) -> dict[str, Any]:
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    found = [contract for contract in contracts if contract["id"] == contract_id]
    assert found, f"pyproject.toml declares no {contract_id} import contract"
    return found[0]


def _lint(root: Path, owner: tuple[str, str, str, str], outsider: str) -> subprocess.CompletedProcess[str]:
    """Lint a `fixture` package shaped like starpulse's, under the real contract with its module names retargeted."""
    contract_id, name, user, table = owner
    package = root / "fixture" / "event_log"
    (package / name).mkdir(parents=True)
    for init in (root / "fixture", package, package / name):
        (init / "__init__.py").write_text("")
    (package / name / "tables.py").write_text(f"{table} = object()\n")
    (package / name / f"{user}.py").write_text(f"from fixture.event_log.{name}.tables import {table}\n")
    (package / "other.py").write_text(outsider)
    contract = json.loads(json.dumps(_contract(contract_id)).replace("starpulse", "fixture"))
    config = root / "contract.toml"
    config.write_text(
        '[tool.importlinter]\nroot_package = "fixture"\n[[tool.importlinter.contracts]]\n'
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in contract.items())
        + "\n"
    )
    lint_imports = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    return subprocess.run([lint_imports, "--config", str(config)], cwd=root, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("owner", _OWNERS, ids=[owner[1] for owner in _OWNERS])
def test_a_module_outside_the_owner_importing_its_tables_breaks_the_contract(
    tmp_path: Path, owner: tuple[str, str, str, str]
) -> None:
    _, name, _, table = owner
    result = _lint(tmp_path, owner, f"from fixture.event_log.{name}.tables import {table}\n")

    assert result.returncode != 0
    assert "fixture.event_log.other" in result.stdout


@pytest.mark.parametrize("owner", _OWNERS, ids=[owner[1] for owner in _OWNERS])
@pytest.mark.parametrize("outsider", ["from fixture.event_log.{name} import {user}\n", "x = 1\n"])
def test_the_owner_package_and_modules_that_use_it_keep_the_contract(
    tmp_path: Path, owner: tuple[str, str, str, str], outsider: str
) -> None:
    result = _lint(tmp_path, owner, outsider.format(name=owner[1], user=owner[2]))

    assert result.returncode == 0, result.stdout
