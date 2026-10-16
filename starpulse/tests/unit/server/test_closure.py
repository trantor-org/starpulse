"""`code_of` and `Reader` read what a `starpulse` process would run from the installed files, in a fresh interpreter."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from starpulse._internal.server import closure
from starpulse._internal.server.closure import SELF, Reader, ReloadError, code_of


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An installed package `demo` whose `entry` imports `demo.used` and not `demo.unused`."""
    root = tmp_path / "demo"
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "entry.py").write_text("from demo import used\n")
    (root / "used.py").write_text("VALUE = 1\n")
    (root / "unused.py").write_text("VALUE = 2\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return root


def test_the_closure_is_the_files_of_the_modules_the_entry_loads_with_their_hashes(package: Path) -> None:
    code = code_of("demo.entry", "demo")

    assert code == {
        (str(package / name), sha256((package / name).read_bytes()).hexdigest())
        for name in ("__init__.py", "entry.py", "used.py")
    }


def test_editing_a_loaded_module_changes_the_closure_and_editing_an_unloaded_one_does_not(package: Path) -> None:
    before = code_of("demo.entry", "demo")

    (package / "unused.py").write_text("VALUE = 3\n")
    assert code_of("demo.entry", "demo") == before

    (package / "used.py").write_text("VALUE = 3\n")
    assert code_of("demo.entry", "demo") != before


def test_an_entry_that_does_not_import_is_a_reload_error_naming_why(package: Path) -> None:
    (package / "entry.py").write_text("raise RuntimeError('half-written')\n")

    with pytest.raises(ReloadError, match="half-written"):
        code_of("demo.entry", "demo")


def test_the_pulls_closure_holds_no_autopilot_module_and_the_autopilot_closure_holds_them() -> None:
    reader = Reader(None)

    pulls = {Path(file).name for file, _ in reader("pulls").code}
    autopilot = {Path(file).name for file, _ in reader("autopilot").code}

    assert "loop.py" not in pulls
    assert {"loop.py", "autopilot_worker.py"} <= autopilot
    assert "supervisor.py" in {Path(file).name for file, _ in reader(SELF).code}


def _toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


@pytest.fixture
def no_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closure, "code_of", lambda entry, package="starpulse": frozenset({(entry, "hash")}))


@pytest.mark.usefixtures("no_code")
def test_a_delivery_setting_is_a_live_change_to_pulls_and_leaves_autopilot_and_serve_unchanged(tmp_path: Path) -> None:
    path = _toml(tmp_path, "")
    before = Reader(path)
    old = {name: before(name) for name in ("pulls", "autopilot", SELF)}
    _toml(tmp_path, "pull_requests = false\n")

    new = {name: before(name) for name in ("pulls", "autopilot", SELF)}

    assert (new["pulls"].live, new["pulls"].restart) != (old["pulls"].live, old["pulls"].restart)
    assert new["pulls"].restart == old["pulls"].restart
    assert new["autopilot"] == old["autopilot"]
    assert new[SELF] == old[SELF]


@pytest.mark.usefixtures("no_code")
def test_the_database_is_a_restart_change_to_both_workers(tmp_path: Path) -> None:
    path = _toml(tmp_path, "")
    reader = Reader(path)
    old = {name: reader(name) for name in ("pulls", "autopilot")}
    _toml(tmp_path, 'database_url = "sqlite:///other.db"\n')

    new = {name: reader(name) for name in ("pulls", "autopilot")}

    assert all(new[n].restart != old[n].restart and new[n].live == old[n].live for n in old)


@pytest.mark.usefixtures("no_code")
def test_a_config_that_does_not_load_is_a_reload_error(tmp_path: Path) -> None:
    path = _toml(tmp_path, "")
    reader = Reader(path)
    path.write_text("pull_requests = [\n")

    with pytest.raises(ReloadError, match="starpulse.toml"):
        reader("pulls")
