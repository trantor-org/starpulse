"""A read verb starts without importing the server, the event log or its database layer."""

import subprocess
import sys

import pytest

HEAVY = (
    "statemachine",
    "jsonschema",
    "sqlalchemy",
    "starpulse.runtime",
    "starpulse.views",
    "starpulse.event_log.event_log",
)

#: The root config loader and its settings model, which `runtime` owns (spec doc-966, D6), and the stdlib-only Page API
#: defaults it reads, light enough for a read verb.
CONFIG = (
    "starpulse.runtime",
    "starpulse.runtime.config",
    "starpulse.runtime.config_model",
    "starpulse.views",
    "starpulse.views.ports",
    "starpulse.views.ports.services",
)

UNREACHABLE = "http://127.0.0.1:1"


@pytest.mark.parametrize("verb", [["board"], ["task", "show", "PROJ-1"]])
def test_a_read_verb_leaves_the_server_and_database_layer_unimported(verb: list[str]) -> None:
    code = (
        "import sys\n"
        "from starpulse.__main__ import main\n"
        f"main({[*verb, '--server', UNREACHABLE]!r})\n"
        f"heavy, config = {HEAVY!r}, {CONFIG!r}\n"
        "print(sorted(name for name in sys.modules if name not in config\n"
        "             and any(name == h or name.startswith(h + '.') for h in heavy)))\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip().splitlines()[-1] == "[]"


@pytest.mark.parametrize("argv", [["task", "create", "--help"], ["migrate", "--help"]])
def test_help_imports_neither_the_store_nor_the_board_assembly(argv: list[str]) -> None:
    code = (
        "import sys\n"
        "from starpulse.__main__ import main\n"
        "try:\n"
        f"    main({argv!r})\n"
        "except SystemExit:\n"
        "    pass\n"
        "print(sorted(name for name in ('sqlalchemy', 'alembic', 'starpulse.runtime.assembly') if name in sys.modules))\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip().splitlines()[-1] == "[]"
