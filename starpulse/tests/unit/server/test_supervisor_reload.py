"""`Supervisor.reload` replaces the children whose closure changed, reloads in place those whose config changed and
re-executes `serve` when its own closure changed."""

from __future__ import annotations

import signal
from collections.abc import Iterator
from typing import Any

import pytest

import starpulse._internal.server.supervisor as supervisor_module
from starpulse._internal.server.closure import SELF, Reading, ReloadError
from starpulse._internal.server.supervisor import Supervisor

NAMES = ("pulls", "autopilot")


class Child:
    """A stand-in `Popen` that runs until it is terminated and records the signals it was sent."""

    made: list[Child] = []

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.pid = 2000 + len(self.made)
        self.signals: list[int] = []
        self.ended = False
        self.made.append(self)

    def poll(self) -> int | None:
        return 0 if self.ended else None

    def send_signal(self, number: int) -> None:
        self.signals.append(number)

    def terminate(self) -> None:
        self.ended = True

    def kill(self) -> None:
        self.ended = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


def reading(code: str = "v1", restart: object = "db", live: object = "config") -> Reading:
    return Reading(frozenset({("module.py", code)}), restart, live)


class Install:
    """What a fresh interpreter reads from the installed code and config; a test edits `now` to change either."""

    def __init__(self) -> None:
        self.now = {name: reading() for name in (*NAMES, SELF)}
        self.broken = False

    def __call__(self, name: str) -> Reading:
        if self.broken:
            raise ReloadError("the installed code does not import")
        return self.now[name]


@pytest.fixture
def install() -> Install:
    return Install()


@pytest.fixture
def executed() -> list[bool]:
    return []


@pytest.fixture
def supervisor(install: Install, executed: list[bool]) -> Iterator[Supervisor]:
    Child.made = []
    running = Supervisor(
        {name: [name] for name in NAMES},
        spawn=Child,
        read=install,
        execute=lambda: executed.append(True),
        poll=60.0,
    )
    running.start()
    yield running
    running.stop()


def test_a_change_in_only_the_autopilot_closure_replaces_only_the_autopilot_child(
    supervisor: Supervisor, install: Install
) -> None:
    before = supervisor.pids()
    install.now["autopilot"] = reading(code="v2")

    report = supervisor.reload()

    after = supervisor.pids()
    assert report == {"supervisor": "kept", "children": {"pulls": "kept", "autopilot": "replaced"}}
    assert after["pulls"] == before["pulls"]
    assert after["autopilot"] != before["autopilot"]
    pulls, autopilot, replacement = Child.made
    assert (pulls.ended, autopilot.ended, replacement.ended) == (False, True, False)


def test_a_change_to_only_the_pulls_config_block_keeps_the_pid_and_asks_it_to_reload(
    supervisor: Supervisor, install: Install
) -> None:
    before = supervisor.pids()
    install.now["pulls"] = reading(live="new config")

    report = supervisor.reload()

    pulls, autopilot = Child.made
    assert report == {"supervisor": "kept", "children": {"pulls": "reloaded", "autopilot": "kept"}}
    assert supervisor.pids() == before
    assert (pulls.signals, autopilot.signals) == ([signal.SIGHUP], [])
    assert not pulls.ended


def test_a_config_block_a_running_child_cannot_take_in_place_replaces_it(
    supervisor: Supervisor, install: Install
) -> None:
    install.now["pulls"] = reading(restart="another database")

    report = supervisor.reload()

    assert report["children"] == {"pulls": "replaced", "autopilot": "kept"}
    assert Child.made[0].ended
    assert len(Child.made) == 3


def test_a_platform_with_no_sighup_replaces_the_child_to_apply_a_config_change(
    supervisor: Supervisor, install: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor_module, "_HANGUP", None)
    install.now["pulls"] = reading(live="new config")

    report = supervisor.reload()

    assert report["children"]["pulls"] == "replaced"
    assert Child.made[0].signals == []


def test_a_change_to_the_supervisors_own_closure_ends_every_child_and_re_executes_after_the_reply(
    supervisor: Supervisor, install: Install, executed: list[bool]
) -> None:
    install.now[SELF] = reading(code="v2")

    report = supervisor.reload()

    assert report == {"supervisor": "re-executed", "children": {"pulls": "replaced", "autopilot": "replaced"}}
    assert [child.ended for child in Child.made] == [True, True]
    assert executed == []
    supervisor.reexec()
    assert executed == [True]


def test_a_reload_with_nothing_changed_keeps_everything_and_the_next_one_compares_with_the_last(
    supervisor: Supervisor, install: Install
) -> None:
    kept = {"supervisor": "kept", "children": {"pulls": "kept", "autopilot": "kept"}}
    assert supervisor.reload() == kept
    install.now["autopilot"] = reading(code="v2")
    assert supervisor.reload()["children"]["autopilot"] == "replaced"
    assert supervisor.reload() == kept
    assert len(Child.made) == 3


def test_a_reading_that_fails_replaces_and_signals_nothing(supervisor: Supervisor, install: Install) -> None:
    install.broken = True

    with pytest.raises(ReloadError):
        supervisor.reload()

    assert [(child.ended, child.signals) for child in Child.made] == [(False, []), (False, [])]


def test_a_child_waiting_to_restart_is_started_at_once_when_its_closure_changed(
    supervisor: Supervisor, install: Install
) -> None:
    pulls, _ = Child.made
    pulls.ended = True
    supervisor.tick(1.0)  # notes the exit; the child is due again only at 2.0
    assert "pulls" not in supervisor.pids()
    install.now["pulls"] = reading(code="v2")

    report = supervisor.reload()

    assert report["children"]["pulls"] == "replaced"
    assert supervisor.pids()["pulls"] == Child.made[-1].pid


def test_a_supervisor_whose_baseline_could_not_be_read_replaces_its_children_on_the_first_reload(
    install: Install, executed: list[bool]
) -> None:
    Child.made = []
    install.broken = True
    running = Supervisor(
        {"pulls": ["pulls"]}, spawn=Child, read=install, execute=lambda: executed.append(True), poll=60
    )
    running.start()
    install.broken = False

    report: dict[str, Any] = running.reload()
    running.stop()

    assert report == {"supervisor": "kept", "children": {"pulls": "replaced"}}
    assert executed == []


def _retiring(install: Install) -> tuple[Supervisor, list[str]]:
    Child.made = []
    events: list[str] = []

    def spawn(command: list[str]) -> Child:
        events.append("spawn")
        return Child(command)

    running = Supervisor(
        {name: [name] for name in NAMES},
        spawn=spawn,
        retire=lambda: events.append("retire"),
        read=install,
        poll=60.0,
    )
    running.start()
    return running, events


def test_a_reload_that_changes_a_childs_code_retires_the_preloaded_process_before_the_replacement_starts(
    install: Install,
) -> None:
    running, events = _retiring(install)
    install.now["pulls"] = reading("v2")

    running.reload()
    running.stop()

    assert events == ["spawn", "spawn", "retire", "spawn"]


def test_a_reload_that_changes_only_config_leaves_the_preloaded_process_alone(install: Install) -> None:
    running, events = _retiring(install)
    install.now["pulls"] = reading(live="other")

    running.reload()
    running.stop()

    assert events == ["spawn", "spawn"]
