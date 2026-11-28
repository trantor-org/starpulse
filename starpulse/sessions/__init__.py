"""What an agent session did: the Activity of each tool call.

`activities` is the classification every tool signal StarPulse stores carries
(`starpulse.harness_telemetry.model.activity`): one tool call lifted to labels with no arguments, so the same work recurs
across sessions. A non-shell tool is its bare name, `TOOL_OTHER` when its name is not one; each statement of a shell
call (a tool in `SHELLS`) is its leading command, such as `bin/<script>`, `make <target>`, `git <subcommand>`,
`gh <group> <verb>` or `ssh <host>`, with `SHELL_READ` and `SHELL_SEARCH` for a file read or a search and `SHELL_OTHER`
for a command that is not a name.

The names resolve on first read, so importing a `starpulse.sessions` submodule runs nothing here and the coverage map
names only the tests that read them.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.harness_telemetry.model.activity import (
        SHELL_OTHER,
        SHELL_READ,
        SHELL_SEARCH,
        SHELLS,
        TOOL_OTHER,
        activities,
    )

__all__ = ["SHELLS", "SHELL_OTHER", "SHELL_READ", "SHELL_SEARCH", "TOOL_OTHER", "activities"]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module("starpulse.harness_telemetry.model.activity"), name)
