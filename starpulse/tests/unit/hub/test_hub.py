"""Hub mode's start-up rules: `serve --hub` needs a Postgres `database_url` and refuses anything else before serving."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import starpulse._internal.hub
from starpulse._internal.server import server

needs_extras = pytest.mark.skipif(
    importlib.util.find_spec("alembic") is None, reason="the hub extras are not installed"
)


_OIDC = """
[oidc]
issuer = "https://id.example.test/realm"
client_id = "starpulse-hub"
client_secret_env = "HUB_OIDC_SECRET"
redirect_uri = "https://hub.example.test/auth/callback"
allowed_groups = ["ops"]
"""


@pytest.fixture(autouse=True)
def _client_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_OIDC_SECRET", "hub-secret")


def _serve_hub(tmp_path: Path, config_text: str, oidc: str | None = _OIDC, argv: tuple[str, ...] = ("--hub",)) -> int | str | None:
    """The exit code of `serve --hub` on a config with `config_text` and the `oidc` table (none: no sign-in)."""
    config = tmp_path / "starpulse.toml"
    config.write_text(config_text + (oidc or ""))
    with pytest.raises(SystemExit) as exited:
        server.main([*argv, "--config", str(config)])
    return exited.value.code


def test_a_hub_without_the_hub_extras_names_the_extra_to_install(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(sys.modules, "starpulse._internal.hub.hub", raising=False)
    monkeypatch.delattr(starpulse._internal.hub, "hub", raising=False)  # `from starpulse._internal.hub import hub` finds the attribute first
    monkeypatch.setitem(sys.modules, "alembic", None)  # importing it raises, as on a machine without the extras

    assert _serve_hub(tmp_path, f'database_url = "postgresql+psycopg://h/{tmp_path.name}"\n') == 1
    assert "pip install 'starpulse[hub]'" in capsys.readouterr().err


@needs_extras
def test_a_hub_without_a_database_url_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = _serve_hub(tmp_path, "")

    assert code == 1
    assert "hub mode needs a Postgres database_url" in capsys.readouterr().err


@needs_extras
def test_a_hub_whose_database_cannot_be_reached_exits_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _serve_hub(tmp_path, 'database_url = "postgresql+psycopg://127.0.0.1:1/hub"\n') == 1
    assert "cannot bring the hub database to the latest schema" in capsys.readouterr().err


@needs_extras
def test_a_hub_on_a_sqlite_database_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = _serve_hub(tmp_path, f'database_url = "sqlite:///{tmp_path / "h.sqlite"}"\n')

    assert code == 1
    assert "hub mode needs a Postgres database_url" in capsys.readouterr().err
    assert not (tmp_path / "h.sqlite").exists()  # refused before anything opened the database


@needs_extras
def test_a_hub_without_an_oidc_table_is_refused_before_the_database_is_touched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _serve_hub(tmp_path, 'database_url = "postgresql+psycopg://127.0.0.1:1/hub"\n', oidc=None)

    assert code == 1
    assert "hub mode needs an [oidc] table" in capsys.readouterr().err


@needs_extras
def test_a_hub_whose_client_secret_variable_is_unset_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HUB_OIDC_SECRET")

    assert _serve_hub(tmp_path, 'database_url = "postgresql+psycopg://127.0.0.1:1/hub"\n') == 1
    assert "HUB_OIDC_SECRET is not set" in capsys.readouterr().err


def test_an_instance_that_is_not_a_hub_refuses_an_oidc_table_rather_than_serving_ungated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _serve_hub(tmp_path, "", argv=()) == 1
    assert "[oidc] gates a hub" in capsys.readouterr().err


_IC_RUN = """
import sys
for name in ("alembic", "psycopg", "jwt"):
    sys.modules[name] = None  # an import of either raises ImportError, as on a machine without the hub extras

import tempfile, threading
from pathlib import Path

from starpulse import __main__

from starpulse._internal.server import server

from starpulse._internal.eventlog import events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore, record_machine_events
from starpulse.tests.machines import MACHINES

url = f"sqlite:///{Path(tempfile.mkdtemp()) / 'ic.sqlite'}"
log = EventLog(url)
events.publish("in-progress", "WORKTREE_READY", actor="t", task="IC-1", now=1.0, log=log)
store = HistoryStore(url, MACHINES)
stop = threading.Event()
threading.Timer(1.0, stop.set).start()
record_machine_events(store, log, stop, interval=0.05)
assert store.machine_path("IC-1", "in-progress")[1] == 1
assert "starpulse._internal.hub.hub" not in sys.modules, "IC mode imported the hub module"
assert "starpulse._internal.hub.oidc" not in sys.modules, "IC mode imported the sign-in module"
"""


def test_ic_mode_runs_without_the_hub_extras_and_never_imports_the_hub_module() -> None:
    ran = subprocess.run([sys.executable, "-I", "-c", _IC_RUN], capture_output=True, text=True, timeout=60)

    assert ran.returncode == 0, ran.stderr
