"""The `worker` entry point imports no scheduler module, so a change to the scheduler restarts only its own worker."""

import json
import subprocess
import sys
from pathlib import Path

import starpulse

ROOT = Path(starpulse.__file__).parents[1]
PROBE = (
    "import json, sys, starpulse._internal.server.worker;"
    "print(json.dumps(sorted(m for m in sys.modules if m.startswith('starpulse._internal.scheduler.'))))"
)


def test_importing_the_worker_entry_loads_no_scheduler_module() -> None:
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(done.stdout) == []
