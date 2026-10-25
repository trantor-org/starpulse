"""The generic harness machine: one agent session's start, the skills and tools it uses, and its stop.

Any harness adapter (Codex, Claude Code) writes events on this one machine, so it depends on no
project's hooks or conventions. `machines/harness.yaml` declares it; its `bindings` name the hook
events a harness fires (`SessionStart`, `PostToolUse`, `Stop`) that move it.
"""

from pathlib import Path

from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.snapshot import describe

#: The machine files beside the package: `adapters/harnesses/` is two levels below them.
MACHINES = Path(__file__).parents[1] / "machines"
HARNESS = load_machine(MACHINES / "harness.yaml")
#: The machine as the page draws it, keyed by name like a board adapter's machines.
SESSION_MACHINES = {HARNESS.name: describe(HARNESS.machine)}
