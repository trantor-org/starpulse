"""`import starpulse.board` and a native board load are a board read's entry point, so they build neither the state machine
nor the adapter models."""

import os
import subprocess
import sys
from pathlib import Path

import starpulse

_PACKAGE_ROOT = Path(starpulse.__file__).resolve().parent.parent

# `statemachine` and `jsonschema` are what compiling a machine definition costs; `pydantic` is the adapter models'.
_HEAVY = (
    "starpulse.machine_engine.model.machine_definition",
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


def test_loading_a_native_board_loads_no_adapter_models(tmp_path: Path) -> None:
    root = tmp_path / "board"
    root.mkdir()
    (root / "config.yml").write_text("project_name: demo\nstatuses: [To Do, Done]\ntask_prefix: task\n")
    code = (
        "from pathlib import Path\n"
        "import starpulse.board\n"
        f"board = starpulse.board.load('native', {{'path': 'board'}}, Path({str(tmp_path)!r}))\n"
        "assert board.keys is not None and board.keys.matches('task-3')\n"
    )

    assert _loaded_after(code) == set()
