"""A read verb starts without importing the server, the event log or its database layer."""

import subprocess
import sys

import pytest

HEAVY = (
    "statemachine",
    "jsonschema",
    "sqlalchemy",
    "starpulse._internal.server",
    "starpulse._internal.eventlog.event_log",
)

UNREACHABLE = "http://127.0.0.1:1"


@pytest.mark.parametrize("verb", [["board"], ["task", "show", "PROJ-1"]])
def test_a_read_verb_leaves_the_server_and_database_layer_unimported(verb: list[str]) -> None:
    code = (
        "import sys\n"
        "from starpulse.__main__ import main\n"
        f"main({[*verb, '--server', UNREACHABLE]!r})\n"
        f"heavy = {HEAVY!r}\n"
        "print(sorted(name for name in sys.modules if any(name == h or name.startswith(h + '.') for h in heavy)))\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip().splitlines()[-1] == "[]"
