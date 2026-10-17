"""No two tracked web sources share a stem that differs only by case: they collide on a case-insensitive filesystem (macOS)."""

from __future__ import annotations

import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_two_web_sources_differ_only_by_case():
    tracked = subprocess.run(
        ["git", "ls-files", "starpulse/web/src"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    stems = defaultdict(set)
    for path in tracked:
        stem = path.removesuffix(Path(path).suffix)
        stems[stem.lower()].add(stem)
    assert {key: sorted(names) for key, names in stems.items() if len(names) > 1} == {}
