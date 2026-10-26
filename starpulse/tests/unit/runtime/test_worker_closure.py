"""The `worker` entry point imports no scheduler module but the `[scheduler]` config section every config load parses,
so a change to the scheduler restarts only its own worker."""

import json
import subprocess
import sys
from pathlib import Path

import starpulse

ROOT = Path(starpulse.__file__).parents[1]
#: The `[scheduler]` section the root config loader parses (spec doc-966, D6), which every process that loads the config
#: imports.
SECTION = ("starpulse.scheduler.model", "starpulse.scheduler.model.config")

PROBE = (
    "import json, sys, starpulse.runtime.worker;"
    "print(json.dumps(sorted(m for m in sys.modules if m.startswith('starpulse.scheduler.'))))"
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

    assert [module for module in json.loads(done.stdout) if module not in SECTION] == []
