"""The generic harness machine: one agent session's start, the skills and tools it uses, and its stop.

Any harness adapter (Codex, Claude Code) writes events on this one machine, so it depends on no
project's hooks or conventions. `machines/harness.yaml` declares it; its `bindings` name the hook
events a harness fires (`SessionStart`, `PostToolUse`, `Stop`) that move it.
"""

from pathlib import Path

from starpulse.domain.machine_definition import load_machine
from starpulse.domain.snapshot import describe

HARNESS = load_machine(Path(__file__).with_name("machines") / "harness.yaml")
#: The machine as the page draws it, keyed by name like a board adapter's machines.
HARNESS_MACHINES = {HARNESS.name: describe(HARNESS.machine)}
