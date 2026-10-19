"""An xdist run starts one mock issuer for all its workers, and stops it when the run ends."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from starpulse.tests.mock_issuer import IMAGE

_ROOT = Path(__file__).parents[4]

_CASES = """
import time
from pathlib import Path

import pytest

SEEN = Path({seen!r})
IMAGE = {image!r}


@pytest.mark.parametrize("n", range(8))
def test_case(n, issuer):
    from testcontainers.core.container import DockerContainer  # noqa: F401
    import subprocess

    ids = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"ancestor={{IMAGE}}"], capture_output=True, text=True, check=True
    ).stdout.split()
    with SEEN.open("a") as seen:
        seen.write(f"{{issuer}} {{','.join(ids)}}\\n")
    time.sleep(0.5)
"""


def _issuer_containers() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"ancestor={IMAGE}"], capture_output=True, text=True, check=True
    )
    return result.stdout.split()


@pytest.mark.slow
def test_four_workers_share_one_issuer_container_that_is_gone_afterwards(tmp_path: Path):
    before = set(_issuer_containers())
    seen = tmp_path / "seen"
    cases = tmp_path / "test_cases.py"
    cases.write_text(textwrap.dedent(_CASES).format(seen=str(seen), image=IMAGE))
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "starpulse.tests.conftest",
            "-n",
            "4",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(_ROOT),
            str(cases),
        ],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(_ROOT / "ci"), os.environ.get("PYTHONPATH", "")])},
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    rows = [line.split() for line in seen.read_text().splitlines()]
    assert len(rows) == 8
    assert len({address for address, _ in rows}) == 1
    started = {container for _, ids in rows for container in ids.split(",")} - before
    assert len(started) == 1
    assert not started & set(_issuer_containers())
