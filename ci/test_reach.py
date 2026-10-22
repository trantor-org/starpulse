"""Which pull-request checks a change reaches (ci/reach.py): the paths each check reads, and those that run all of them."""

from __future__ import annotations

import pytest
from reach import reaches, scope


@pytest.mark.parametrize("check", ["web", "static"])
@pytest.mark.parametrize(
    "path", ["uv.lock", "pyproject.toml", "starpulse/web/pnpm-lock.yaml", ".github/workflows/ci.yml"]
)
def test_a_dependency_or_ci_config_change_reaches_every_check(check, path):
    assert reaches(check, [path])


def test_a_change_of_no_files_reaches_nothing():
    assert not any(scope([]).values())


def test_a_docs_edit_reaches_only_the_static_checks():
    assert scope(["docs/ci.md"]) == {"web": False, "static": True}


def test_a_python_module_reaches_static_but_not_web():
    assert scope(["starpulse/board.py"]) == {"web": False, "static": True}


def test_the_api_schema_reaches_web():
    assert reaches("web", ["starpulse/api.schema.json"])
