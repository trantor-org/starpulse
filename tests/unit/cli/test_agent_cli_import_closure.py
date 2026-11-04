"""The agent CLI's verbs that show no move verdict import no pydantic model, so each `starpulse task ...` call
skips ~0.25 CPU-s of model building; the board's move verdict loads `starpulse.contracts.adapters` on first use."""

import subprocess
import sys
from pathlib import Path

import starpulse

ROOT = Path(starpulse.__file__).parents[1]

PROBE = (
    "import sys, starpulse.cli.agent_tasks;"
    "print(sorted(m for m in ('pydantic', 'starpulse.contracts.adapters') if m in sys.modules))"
)


def test_importing_the_agent_task_verbs_loads_no_pydantic_model() -> None:
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert done.stdout.strip() == "[]"
