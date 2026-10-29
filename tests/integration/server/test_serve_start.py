"""What `serve` has loaded when it starts its first child: the page waits on that child, so each import before it is page latency."""

import json
import subprocess
import sys

import pytest
from starpulse.runtime import server

from tests.page_stub import held
from tests.stores import migrate_config_store

# Loading the database stack is the second a start spends: the Page API child pays it, and `serve` checks the config
# against it only once the children run.
_NOT_YET = ("sqlalchemy", "alembic", "starpulse.runtime.assembly")
# Package `__init__` modules count: each role subpackage of a context adds one to what a start loads.
_STARPULSE_MODULES = 160

_FIRST_CHILD = """
import json, sys
from starpulse.runtime import server, supervisor


def first_child(self):
    print(json.dumps(sorted(sys.modules)))
    sys.exit(0)


supervisor.Supervisor.start = first_child
server.main(["--port", "0", "--config", sys.argv[1]])
"""


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """The modules `serve` holds when its supervisor is asked to start the first child."""
    config = tmp_path_factory.mktemp("first-child") / "starpulse.toml"
    config.write_text("")
    migrate_config_store(config)
    with held(server._STATIC):
        run = subprocess.run(
            [sys.executable, "-c", _FIRST_CHILD, str(config)], capture_output=True, text=True, timeout=60, check=False
        )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.splitlines()[-1])


def test_serve_has_not_loaded_the_database_stack_when_its_first_child_starts(loaded: list[str]) -> None:
    assert [name for name in loaded if name.split(".")[0] in _NOT_YET or name in _NOT_YET] == []


def test_serve_has_loaded_few_starpulse_modules_when_its_first_child_starts(loaded: list[str]) -> None:
    assert len([name for name in loaded if name.startswith("starpulse")]) < _STARPULSE_MODULES
