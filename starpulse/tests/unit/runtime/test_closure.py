"""`code_of` and `Reader` read what a `starpulse` process would run from the installed files, in a fresh interpreter."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from starpulse.runtime import closure
from starpulse.runtime.closure import SELF, Reader, Reading, ReloadError, code_of, package_hashes
from starpulse.runtime.supervisor import WORKER_FLAGS


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


def _closure_names(entry: str) -> set[str]:
    return {Path(file).name for file, _ in Reader(None)(entry).code}


def test_the_pulls_closure_holds_no_scheduler_module() -> None:
    assert "loop.py" not in _closure_names("pulls")


def test_the_scheduler_closure_holds_the_scheduler_modules() -> None:
    assert {"loop.py", "scheduler_worker.py"} <= _closure_names("scheduler")


def test_the_serve_closure_holds_the_supervisor() -> None:
    assert "supervisor.py" in _closure_names(SELF)


def _toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


@pytest.fixture
def no_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closure, "code_of", lambda entry, package="starpulse": frozenset({(entry, "hash")}))


@pytest.mark.usefixtures("no_code")
def test_a_delivery_setting_is_a_live_change_to_pulls_and_leaves_scheduler_and_serve_unchanged(tmp_path: Path) -> None:
    path = _toml(tmp_path, "")
    before = Reader(path)
    old = {name: before(name) for name in ("pulls", "scheduler", SELF)}
    _toml(tmp_path, "pull_requests = false\n")

    new = {name: before(name) for name in ("pulls", "scheduler", SELF)}

    assert (new["pulls"].live, new["pulls"].restart) != (old["pulls"].live, old["pulls"].restart)
    assert new["pulls"].restart == old["pulls"].restart
    assert new["scheduler"] == old["scheduler"]
    assert new[SELF] == old[SELF]


def test_every_supervised_worker_has_a_closure_entry() -> None:
    assert set(WORKER_FLAGS) <= set(closure.ENTRIES)


@pytest.mark.usefixtures("no_code")
def test_the_database_is_a_restart_change_to_every_worker(tmp_path: Path) -> None:
    path = _toml(tmp_path, "")
    reader = Reader(path)
    old = {name: reader(name) for name in WORKER_FLAGS}
    _toml(tmp_path, 'database_url = "sqlite:///other.db"\n')

    new = {name: reader(name) for name in WORKER_FLAGS}

    assert all(new[n].restart != old[n].restart and new[n].live == old[n].live for n in old)


@pytest.mark.usefixtures("no_code")
def test_a_config_that_does_not_load_is_a_reload_error(tmp_path: Path) -> None:
    path = _toml(tmp_path, "")
    reader = Reader(path)
    path.write_text("pull_requests = [\n")

    with pytest.raises(ReloadError, match="starpulse.toml"):
        reader("pulls")


def test_a_start_reading_is_unchanged_while_every_closure_file_keeps_the_hash_it_had_at_start() -> None:
    start = Reading(frozenset(), "db", "config", files={"a.py": "1", "b.py": "2", "unused.py": "3"})

    assert start.same_code(Reading(frozenset({("a.py", "1"), ("b.py", "2")}), "db", "config"))
    assert not start.same_code(Reading(frozenset({("a.py", "1"), ("b.py", "changed")}), "db", "config"))
    assert not start.same_code(Reading(frozenset({("a.py", "1"), ("new.py", "9")}), "db", "config"))


def test_a_full_reading_compares_its_closure_to_the_new_one() -> None:
    old = Reading(frozenset({("a.py", "1")}), "db", "config")

    assert old.same_code(Reading(frozenset({("a.py", "1")}), "db", "config"))
    assert not old.same_code(Reading(frozenset({("a.py", "1"), ("b.py", "2")}), "db", "config"))


def test_the_start_reading_runs_no_probe_and_its_hashes_cover_the_files_a_closure_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = Reader(None)
    probes = []
    monkeypatch.setattr(closure, "code_of", lambda entry, package="starpulse": probes.append(entry))

    start = reader.at_start("pulls")

    assert probes == []
    monkeypatch.undo()
    assert dict(reader("pulls").code).items() <= start.files.items()


def test_package_hashes_name_each_module_file_of_the_package_with_its_content_hash(
    package: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(package.parent))
    hashes = package_hashes("demo")

    assert hashes[str(package / "unused.py")] == sha256((package / "unused.py").read_bytes()).hexdigest()
    assert set(hashes) == {str(package / name) for name in ("__init__.py", "entry.py", "used.py", "unused.py")}


@pytest.mark.parametrize("entry", list(closure.ENTRIES))
def test_every_entry_reads_the_board_adapter_module_the_config_maps_its_type_to(entry: str) -> None:
    assert any(file.endswith("starpulse/board/adapters/native.py") for file, _ in Reader(None)(entry).code)


def test_a_board_type_that_names_no_module_is_a_reload_error() -> None:
    with pytest.raises(ReloadError, match="nowhere"):
        closure.board_adapter_code("nowhere")
