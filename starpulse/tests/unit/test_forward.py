"""What an IC forwards: only the fields the contract allows, and a person's name only after opt-in."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from starpulse.adapters.runs import run_events
from starpulse.api import forward
from starpulse.api.forward import OPT_IN_FILE, OptIn, build, project, start
from starpulse.settings.config import Config, Forward
from starpulse.store import events
from starpulse.store.event_log import EventLog
from starpulse.store.history import HistoryStore

MACHINE_ENTRY = {
    "machine": "board",
    "event": "MOVED",
    "task": "TASK-1",
    "actor": "adin",
    "assignee": "adin",
    "time": 100.0,
    "title": "Fix the thing",
}
RUN_ENTRY = {
    "time": 100.0,
    "phase": "end",
    "workflow": "nightly",
    "run_id": "r1",
    "status": "succeeded",
    "step": "load",
    "depends": ["fetch"],
    "instance": "adin-laptop",
}


def test_a_machine_event_without_opt_in_loses_actor_assignee_and_unknown_fields() -> None:
    sent = project(events.STREAM, MACHINE_ENTRY, opt_in=False)

    assert sent == {"machine": "board", "event": "MOVED", "task": "TASK-1", "time": 100.0}


def test_a_machine_event_with_opt_in_keeps_actor_and_assignee_but_still_no_unknown_fields() -> None:
    sent = project(events.STREAM, MACHINE_ENTRY, opt_in=True)

    assert sent == {
        "machine": "board",
        "event": "MOVED",
        "task": "TASK-1",
        "actor": "adin",
        "assignee": "adin",
        "time": 100.0,
    }


def test_a_run_event_keeps_its_contract_fields_and_leaves_the_local_instance_behind() -> None:
    sent = project(run_events.STREAM, RUN_ENTRY, opt_in=False)

    assert sent == {k: v for k, v in RUN_ENTRY.items() if k != "instance"}


def test_a_new_instance_is_opted_out(tmp_path: Path) -> None:
    assert OptIn(tmp_path / "starpulse-forward.json").get() is False


def test_opting_in_and_out_is_read_at_once_by_every_reader(tmp_path: Path) -> None:
    path = tmp_path / "starpulse-forward.json"
    reader = OptIn(path)

    OptIn(path).set(True)
    assert reader.get() is True
    OptIn(path).set(False)
    assert reader.get() is False


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"opt_in": "yes"}', '{"opt_in": 1}', "{}"])
def test_a_file_that_does_not_say_true_leaves_the_instance_opted_out(tmp_path: Path, text: str) -> None:
    path = tmp_path / "starpulse-forward.json"
    path.write_text(text)

    assert OptIn(path).get() is False


def test_the_file_holds_one_opt_in_flag(tmp_path: Path) -> None:
    path = tmp_path / "starpulse-forward.json"

    OptIn(path).set(True)

    assert json.loads(path.read_text()) == {"opt_in": True}


def test_the_forward_command_opts_in_and_out_through_the_file_beside_the_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "starpulse.toml"
    flag = OptIn(tmp_path / OPT_IN_FILE)

    assert forward.main(["opt-in", "--config", str(config)]) == 0
    assert flag.get() is True
    assert forward.main(["status", "--config", str(config)]) == 0
    assert "opted in" in capsys.readouterr().out

    assert forward.main(["opt-out", "--config", str(config)]) == 0
    assert flag.get() is False
    assert forward.main(["status", "--config", str(config)]) == 0
    assert "opted out" in capsys.readouterr().out


def test_the_forward_command_without_a_config_flag_uses_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert forward.main(["opt-in"]) == 0

    assert OptIn(tmp_path / OPT_IN_FILE).get() is True


def test_the_forward_command_refuses_an_unknown_action(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        forward.main(["opt-sideways", "--config", str(tmp_path / "starpulse.toml")])

    assert exited.value.code == 2


def _config(forward: Forward | None = None) -> Config:
    return Config(tracker_url=None, mode="ic", runs=(), forward=forward)


def _ic(tmp_path: Path) -> tuple[EventLog, HistoryStore]:
    url = f"sqlite:///{tmp_path / 'ic.sqlite'}"
    return EventLog(url), HistoryStore(url, {})


def test_no_forward_block_builds_no_forwarder(tmp_path: Path) -> None:
    log, store = _ic(tmp_path)

    assert build(_config(), tmp_path, log, store, {}) is None


def test_a_forward_block_starts_a_forwarder_that_stops_with_the_event(tmp_path: Path) -> None:
    log, store = _ic(tmp_path)
    stop = threading.Event()
    config = _config(Forward("http://127.0.0.1:9", "HUB_TOKEN", 50))

    forwarder = build(config, tmp_path, log, store, {"HUB_TOKEN": "secret"})
    assert forwarder is not None
    thread = start(forwarder, stop)

    assert thread is not None and thread.is_alive()
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_a_forward_block_without_its_token_is_refused_by_name(tmp_path: Path) -> None:
    log, store = _ic(tmp_path)
    config = _config(Forward("http://127.0.0.1:9", "HUB_TOKEN", 50))

    with pytest.raises(ValueError, match="HUB_TOKEN is not set"):
        build(config, tmp_path, log, store, {})


def test_a_hub_does_not_forward(tmp_path: Path) -> None:
    log, store = _ic(tmp_path)
    config = _config(Forward("http://127.0.0.1:9", "HUB_TOKEN", 50))

    with pytest.raises(ValueError, match="hub"):
        build(config, tmp_path, log, store, {"HUB_TOKEN": "secret"}, hub=True)
