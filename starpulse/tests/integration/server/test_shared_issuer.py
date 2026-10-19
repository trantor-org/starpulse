"""An xdist run starts one mock issuer for all its workers, and stops it when the run ends."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[4]

_CASES = """
import subprocess
import time
from pathlib import Path

import pytest

SEEN = Path({seen!r})


@pytest.mark.parametrize("n", range(8))
def test_case(n, issuer):
    port = issuer.split(":")[2].split("/")[0]
    ids = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"publish={{port}}"], capture_output=True, text=True, check=True
    ).stdout.split()
    with SEEN.open("a") as seen:
        seen.write(f"{{port}} {{','.join(ids)}}\\n")
    time.sleep(0.5)
"""


def _published_on(port: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"publish={port}"], capture_output=True, text=True, check=True
    )
    return result.stdout.split()


@pytest.mark.slow
def test_four_workers_share_one_issuer_container_that_is_gone_afterwards(tmp_path: Path):
    """Other runs on the host start issuers of their own, so this run's container is the one on the port it was given."""
    seen = tmp_path / "seen"
    cases = tmp_path / "test_cases.py"
    cases.write_text(textwrap.dedent(_CASES).format(seen=str(seen)))
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
    ports = {port for port, _ in rows}
    assert len(ports) == 1
    assert len({ids for _, ids in rows}) == 1
    assert len(rows[0][1].split(",")) == 1
    assert not _published_on(ports.pop())
