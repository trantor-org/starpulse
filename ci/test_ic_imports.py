"""The IC import check: every module an IC instance can load imports without the hub extras."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ic_imports import HUB_ONLY, failures, ic_modules

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"


def test_ic_modules_leave_out_the_hub_only_modules_and_the_tests():
    modules = ic_modules(ROOT)
    assert "starpulse._internal.server.server" in modules
    assert "starpulse._internal.hub.forward" in modules  # `starpulse forward` runs in IC mode
    assert not [m for m in modules if m.startswith(HUB_ONLY) or ".tests" in m]


def test_a_module_that_imports_a_missing_package_is_a_failure(tmp_path, monkeypatch):
    package = tmp_path / "icpkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "fine.py").write_text("import json\n")
    (package / "leaky.py").write_text("import a_hub_only_package_that_is_absent\n")
    monkeypatch.syspath_prepend(tmp_path)
    assert [name for name, _ in failures(["icpkg.fine", "icpkg.leaky"])] == ["icpkg.leaky"]


def test_the_ic_job_runs_the_import_check_without_the_hub_group_and_no_pytest():
    runs = "\n".join(step.get("run", "") for step in yaml.safe_load(CI.read_text())["jobs"]["ic"]["steps"])
    assert "uv sync --locked --no-group hub" in runs
    assert "ci/ic_imports.py" in runs
    assert "pytest" not in runs


@pytest.mark.parametrize("name", list(yaml.safe_load(CI.read_text())["jobs"]))
def test_every_ci_job_has_a_timeout(name):
    assert yaml.safe_load(CI.read_text())["jobs"][name].get("timeout-minutes", 0) > 0
