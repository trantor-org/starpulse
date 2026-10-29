"""`ci/static_checks.sh` runs `lint-imports` among its checks and fails the job when a contract breaks."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "static_checks.sh"


def _run(tmp_path: Path, *, layers_exit: int) -> subprocess.CompletedProcess[str]:
    """The script with `uv` stubbed to succeed, except `lint-imports`, and `pnpm` and `git` stubbed to succeed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "uv": f'case "$*" in *lint-imports*) echo "contract broken"; exit {layers_exit};; esac',
        "pnpm": "",
        "git": "",
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\nexit 0\n")
        stub.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "TMPDIR": str(tmp_path)}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=tmp_path, check=False)


def test_a_broken_import_contract_fails_the_static_checks_and_names_the_check(tmp_path: Path) -> None:
    done = _run(tmp_path, layers_exit=1)

    assert done.returncode == 1
    assert "static check failed: import-layers" in done.stdout
    assert "contract broken" in done.stdout


def test_kept_import_contracts_pass_the_static_checks(tmp_path: Path) -> None:
    done = _run(tmp_path, layers_exit=0)

    assert done.returncode == 0
    assert "::group::import-layers passed" in done.stdout
