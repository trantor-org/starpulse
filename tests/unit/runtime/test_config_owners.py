"""`CONFIG_OWNERS` names who reads each `starpulse.toml` key, so a config change reloads only its owners and restarts `serve`
only for what `serve` itself reads."""

from __future__ import annotations

import signal
from dataclasses import replace
from pathlib import Path

import pytest
from starpulse.runtime import closure
from starpulse.runtime.closure import CONFIG_OWNERS, SELF, _blocks, restarts_serve
from starpulse.runtime.config import _KEYS, load
from starpulse.runtime.supervisor import WORKER_CONTEXTS, Supervisor, worker_commands

CHILDREN = WORKER_CONTEXTS

#: The `Config` attribute each top-level key fills; a key absent here is read through no single attribute.
ATTRIBUTE = {
    "tracker_url": "tracker_url",
    "runs": "runs",
    "repos": "repos",
    "harnesses_file": "harnesses",
    "board": "board",
    "database_url": "database_url",
    "session_start_url": "session_start_url",
    "level": "level",
    "ci": "ci",
    "event_log_retention_days": "event_log_retention_days",
    "event_log_archive_dir": "event_log_archive_dir",
    "scheduler": "scheduler",
    "release": "release",
    "analytics": "analytics",
    "search": "search",
    "cursor_context": "cursor_context",
    "pull_requests": "pull_requests",
    "producers": "producers",
    "sequences": "sequences",
}


def test_every_config_key_has_an_owner() -> None:
    assert _KEYS - CONFIG_OWNERS.keys() == set()
    assert CONFIG_OWNERS.keys() - _KEYS == set()
    assert [key for key, owners in CONFIG_OWNERS.items() if not owners] == []


@pytest.mark.parametrize("key", sorted(ATTRIBUTE))
def test_a_key_is_owned_by_exactly_the_processes_whose_reading_it_changes(key: str) -> None:
    base = load(None)
    changed = replace(base, **{ATTRIBUTE[key]: {"changed": True} if key == "board" else object()})

    moved = {name for name in CHILDREN if _blocks(name, base, Path.cwd()) != _blocks(name, changed, Path.cwd())}

    assert moved == set(CONFIG_OWNERS[key]) - {SELF}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ({"runs": [{"name": "a"}]}, {"runs": [{"name": "a", "domains": {"x": ["y"]}}]}),
        ({"search": {"embeddings_url": "http://a"}}, {"search": {"embeddings_url": "http://b"}}),
        ({"board": {"x": 1}}, {"board": {"x": 2}}),
        ({"ci": {"wait": 1}}, {"ci": {"wait": 2}}),
    ],
)
def test_a_change_to_a_context_owned_table_does_not_restart_serve(old: dict, new: dict) -> None:
    assert restarts_serve(old, new) is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ({}, {"worker_memory": {"contexts": {"soft_mb": 1, "hard_mb": 2}}}),
        ({}, {"mode": "team"}),
        ({}, {"tls_cert": "a.crt", "tls_key": "a.key"}),
        ({}, {"unheard_of": 1}),
    ],
)
def test_a_change_serve_reads_or_that_changes_the_children_restarts_serve(old: dict, new: dict) -> None:
    assert restarts_serve(old, new) is True


@pytest.mark.parametrize("raw", [{}, {"search": {"embeddings_url": "http://a"}}])
def test_the_children_serve_starts_do_not_depend_on_the_config(raw: dict) -> None:
    assert not restarts_serve({}, raw)
    assert list(worker_commands(None)) == ["api", "contexts"]


CONFIG = """
[board]
type = "native"
interval = 1

[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.invalid"
[runs.domains]
Ops = ["nightly", "task-duplicate-retrain"]

[search]
embeddings_url = "http://embed.invalid"
model = "small"
"""

#: Each edit changes one table; the children it must replace are the ones that read that table, and the Page API beside
#: them, which is built from the whole config and swaps behind its socket without dropping a request. `contexts` reads
#: every table a background context reads, so an edit to one of them replaces it as the one process it is.
EDITS = {
    "runs": ('"nightly", "task-duplicate-retrain"', '"nightly"', {"api", "contexts"}),
    "search": ('model = "small"', 'model = "large"', {"api", "contexts"}),
    "board": ("interval = 1", "interval = 2", {"api", "contexts"}),
}


class Child:
    """A stand-in `Popen` that runs until it is terminated, with a pid of its own."""

    made: list[Child] = []

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.pid = 3000 + len(self.made)
        self.ended = False
        self.made.append(self)

    def poll(self) -> int | None:
        return 0 if self.ended else None

    def send_signal(self, number: int) -> None:
        pass

    def terminate(self) -> None:
        self.ended = True

    def kill(self) -> None:
        self.ended = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


@pytest.mark.parametrize("table", EDITS)
def test_a_reload_after_a_change_to_one_table_replaces_only_the_children_that_read_it(
    table: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(closure, "code_of", lambda entry, **_: frozenset())
    path = tmp_path / "starpulse.toml"
    path.write_text(CONFIG)
    Child.made = []
    executed: list[bool] = []
    commands = {name: [name] for name in worker_commands(path)}
    supervisor = Supervisor(
        commands, spawn=Child, read=closure.Reader(path), execute=lambda: executed.append(True), poll=60.0
    )
    supervisor.start()
    try:
        before = {child.command[0]: child.pid for child in Child.made}
        old, new, owners = EDITS[table]
        path.write_text(CONFIG.replace(old, new))

        report = supervisor.reload()

        after = {child.command[0]: child for child in Child.made}
        replaced = {name for name, child in after.items() if child.pid != before[name]}
        assert set(commands) >= owners
        assert {name for name, how in report["children"].items() if how == "replaced"} == owners
        assert replaced == owners
        assert {name for name, child in after.items() if child.pid == before[name] and child.ended} == set()
        assert executed == []
    finally:
        supervisor.stop()


class Signalled(Child):
    """A `Child` that records the signals it is sent."""

    def __init__(self, command: list[str]) -> None:
        super().__init__(command)
        self.signals: list[int] = []

    def send_signal(self, number: int) -> None:
        self.signals.append(number)


def test_a_reload_after_a_live_only_change_keeps_the_contexts_pid_and_hangs_it_up(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(closure, "code_of", lambda entry, **_: frozenset())
    path = tmp_path / "starpulse.toml"
    path.write_text("pull_requests = true\n" + CONFIG)
    Child.made = []
    commands = {name: [name] for name in worker_commands(path)}
    supervisor = Supervisor(commands, spawn=Signalled, read=closure.Reader(path), execute=lambda: None, poll=60.0)
    supervisor.start()
    try:
        contexts = next(child for child in Child.made if child.command == ["contexts"])
        path.write_text("pull_requests = false\n" + CONFIG)

        report = supervisor.reload()

        assert report["children"]["contexts"] == "reloaded"
        assert contexts.signals == [signal.SIGHUP]
        assert not contexts.ended
        assert [child.pid for child in Child.made if child.command == ["contexts"]] == [contexts.pid]
    finally:
        supervisor.stop()
