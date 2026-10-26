"""`CONFIG_OWNERS` names who reads each `starpulse.toml` key, so a config change reloads only its owners and restarts `serve`
only for what `serve` itself reads."""

from __future__ import annotations

from dataclasses import replace

import pytest

from starpulse._internal.config.config import _KEYS, Config, load
from starpulse.runtime import closure
from starpulse.runtime.closure import CONFIG_OWNERS, SELF, _blocks, restarts_serve
from starpulse.runtime.supervisor import WORKER_FLAGS, Supervisor, worker_commands

CHILDREN = tuple(WORKER_FLAGS)

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
}


def test_every_config_key_has_an_owner() -> None:
    assert _KEYS - CONFIG_OWNERS.keys() == set()
    assert CONFIG_OWNERS.keys() - _KEYS == set()
    assert [key for key, owners in CONFIG_OWNERS.items() if not owners] == []


@pytest.mark.parametrize("key", sorted(ATTRIBUTE))
def test_a_key_is_owned_by_exactly_the_processes_whose_reading_it_changes(key: str) -> None:
    base = load(None)
    changed = replace(base, **{ATTRIBUTE[key]: object()})

    moved = {name for name in CHILDREN if _blocks(name, base) != _blocks(name, changed)}

    assert moved == set(CONFIG_OWNERS[key]) - {SELF}


@pytest.mark.parametrize("flag", [flag for flag in WORKER_FLAGS.values() if flag])
def test_a_worker_flag_is_read_by_serve_alone(flag: str) -> None:
    assert CONFIG_OWNERS[flag] == (SELF,)


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
        ({"runs_worker": True}, {"runs_worker": False}),
        ({}, {"worker_memory": {"runs": {"soft_mb": 1, "hard_mb": 2}}}),
        ({}, {"mode": "team"}),
        ({}, {"unheard_of": 1}),
        ({"search": {"embeddings_url": "http://a"}}, {"search": {}}),
    ],
)
def test_a_change_serve_reads_or_that_changes_the_children_restarts_serve(old: dict, new: dict) -> None:
    assert restarts_serve(old, new) is True


@pytest.mark.parametrize(
    "raw",
    [{}, {"search": {"embeddings_url": "http://a"}}],
)
def test_the_structural_rule_agrees_with_the_children_serve_starts(raw: dict, tmp_path) -> None:
    absent: Config = load(None)
    config = replace(absent, search=replace(absent.search, embeddings_url=raw.get("search", {}).get("embeddings_url")))

    assert (worker_commands(config, None) != worker_commands(absent, None)) is restarts_serve({}, raw)


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
#: them, which is built from the whole config and swaps behind its socket without dropping a request.
EDITS = {
    "runs": ('"nightly", "task-duplicate-retrain"', '"nightly"', {"api", "runs"}),
    "search": ('model = "small"', 'model = "large"', {"api", "search"}),
    "board": ("interval = 1", "interval = 2", {"api", "pulls", "scheduler", "runs", "flow-metrics", "board"}),
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
    monkeypatch.setattr(closure, "code_of", lambda entry: frozenset())
    path = tmp_path / "starpulse.toml"
    path.write_text(CONFIG)
    Child.made = []
    executed: list[bool] = []
    config = load(path)
    commands = {name: [name] for name in worker_commands(config, path)}
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
