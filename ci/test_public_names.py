"""The public-repository name check: private host names stay out of tracked files, and the tree holds none."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from public_names import trantor_violations, violations

ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize("name", ["ai-vm-1", "Unraid", "proxmox", "tower", "Tower"])
def test_a_denied_host_name_is_reported_with_its_file_and_line(tmp_path, name):
    path = _write(tmp_path, "docs/serving.md", f"fine\nthe {name} host\n")
    assert violations([path], tmp_path) == [f"docs/serving.md:2: {name}"]


def test_a_neutral_file_and_a_word_that_only_contains_tower_report_nothing(tmp_path):
    path = _write(tmp_path, "docs/a.md", "the build host and a stower of crates\n")
    assert violations([path], tmp_path) == []


@pytest.mark.parametrize(
    "rel",
    [
        ".github/workflows/release.yml",
        ".github/actionlint.yaml",
        "ci/test_x.py",
        "starpulse/tests/unit/test_y.py",
        "starpulse/tests/fixtures/z.json",
    ],
)
def test_workflow_and_test_files_are_exempt(tmp_path, rel):
    assert violations([_write(tmp_path, rel, "runs-on: [self-hosted, tower, ai-vm-1]\n")], tmp_path) == []


def test_a_binary_file_is_skipped(tmp_path):
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG\xff\xfe unraid")
    assert violations([path], tmp_path) == []


def test_the_tracked_tree_holds_no_denied_name():
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [ROOT / p for p in tracked.decode().split("\0") if p]
    assert violations(files, ROOT) == []


@pytest.mark.parametrize("name", ["trantor", "backlog-task", ".venv/bin/", "bin/workspace", "agent-cmd"])
@pytest.mark.parametrize("rel", ["starpulse/skills/review/SKILL.md", "starpulse/machines/board.yaml"])
def test_a_trantor_name_in_a_shipped_skill_or_machine_is_reported(tmp_path, name, rel):
    path = _write(tmp_path, rel, f"fine\nrun {name} here\n")
    assert trantor_violations([path], tmp_path) == [f"{rel}:2: {name}"]


def test_a_trantor_name_outside_shipped_skills_and_machines_is_not_reported(tmp_path):
    paths = [
        _write(tmp_path, "docs/a.md", "run trantor and agent-cmd\n"),
        _write(tmp_path, "starpulse/tests/unit/machines/test_x.py", "trantor\n"),
    ]
    assert trantor_violations(paths, tmp_path) == []


def test_the_tracked_tree_holds_no_trantor_name_in_shipped_skills_or_machines():
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [ROOT / p for p in tracked.decode().split("\0") if p]
    assert trantor_violations(files, ROOT) == []
