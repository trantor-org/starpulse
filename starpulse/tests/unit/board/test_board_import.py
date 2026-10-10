"""`import starpulse.board` is a board read's entry point, so it builds neither the state machine nor the adapter models."""

import os
import subprocess
import sys
from pathlib import Path

import starpulse

_PACKAGE_ROOT = Path(starpulse.__file__).resolve().parent.parent

# `statemachine` and `jsonschema` are what compiling a machine definition costs; `pydantic` is the adapter models'.
_HEAVY = (
    "starpulse._internal.machines.machine_definition",
    "starpulse.contracts.adapters",
    "statemachine",
    "jsonschema",
    "pydantic",
)


def _loaded_after(code: str) -> set[str]:
    """Which of `_HEAVY` a fresh interpreter has in `sys.modules` after running `code`."""
    probe = f"{code}\nimport sys\nprint(*[name for name in {_HEAVY!r} if name in sys.modules])"
    env = {**os.environ, "PYTHONPATH": str(_PACKAGE_ROOT)}
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True)
    return set(done.stdout.split())


def test_importing_the_board_loads_no_machine_definition_or_adapter_models() -> None:
    assert _loaded_after("import starpulse.board") == set()

