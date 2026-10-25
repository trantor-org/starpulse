"""Runs reaching the GitHub transport through Pulls: `lint-imports` refuses a Runs module that imports a Pulls module."""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).parents[4] / "pyproject.toml"


def _lint(root: Path, runs_module: str) -> subprocess.CompletedProcess[str]:
    """Lint a `fixture` package shaped like starpulse's, under the real context-runs contract retargeted to it."""
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    found = [contract for contract in contracts if contract["id"] == "context-runs"]
    assert found, "pyproject.toml declares no context-runs import contract"
    internal = root / "fixture" / "_internal"
    for package in (root / "fixture" / "runs", root / "fixture" / "pulls", internal / "board"):
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
    for init in (root / "fixture", internal):
        (init / "__init__.py").write_text("")
    (root / "fixture" / "pulls" / "github.py").write_text("token = object()\n")
    (internal / "board" / "seam.py").write_text("seam = object()\n")
    (root / "fixture" / "runs" / "ingest.py").write_text(runs_module)
    contract = json.loads(json.dumps(found[0]).replace("starpulse", "fixture"))
    config = root / "contract.toml"
    config.write_text(
        '[tool.importlinter]\nroot_package = "fixture"\n[[tool.importlinter.contracts]]\n'
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in contract.items())
        + "\n"
    )
    lint_imports = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    return subprocess.run(
        [lint_imports, "--config", str(config)], cwd=root, capture_output=True, text=True, check=False
    )


def test_runs_importing_a_pulls_module_breaks_the_contract(tmp_path: Path) -> None:
    result = _lint(tmp_path, "from fixture.pulls.github import token\n")

    assert result.returncode != 0
    assert "fixture.runs.ingest" in result.stdout


@pytest.mark.parametrize("runs_module", ["from fixture._internal.board.seam import seam\n", "x = 1\n"])
def test_runs_importing_board_or_nothing_keeps_the_contract(tmp_path: Path, runs_module: str) -> None:
    result = _lint(tmp_path, runs_module)

    assert result.returncode == 0, result.stdout
