"""`starpulse reload` reaches the running supervisor through its loopback control endpoint and prints what it did."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.server import control
from starpulse._internal.server.closure import ReloadError
from starpulse._internal.server.control import Control

REPORT = {"supervisor": "kept", "children": {"pulls": "kept", "autopilot": "replaced"}}


class FakeSupervisor:
    def __init__(self) -> None:
        self.report: dict[str, Any] = REPORT
        self.failure: ReloadError | None = None
        self.reloads = 0
        self.reexecuted = False

    def reload(self) -> dict[str, Any]:
        self.reloads += 1
        if self.failure:
            raise self.failure
        return self.report

    def reexec(self) -> None:
        self.reexecuted = True


@pytest.fixture
def supervisor() -> FakeSupervisor:
    return FakeSupervisor()


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text("")
    return path


@pytest.fixture
def running(config: Path, supervisor: FakeSupervisor) -> Iterator[Control]:
    endpoint = Control(control.control_file(config), supervisor)
    endpoint.start()
    yield endpoint
    endpoint.stop()


def test_the_control_file_sits_beside_the_config_else_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert control.control_file(tmp_path / "etc" / "starpulse.toml") == tmp_path / "etc" / "starpulse.control"
    assert control.control_file(None) == tmp_path / "starpulse.control"


def test_two_configs_in_one_directory_keep_separate_control_files(tmp_path: Path) -> None:
    live = control.control_file(tmp_path / "starpulse.toml")
    hub = control.control_file(tmp_path / "starpulse-hub.toml")

    assert live != hub
    assert hub == tmp_path / "starpulse-hub.control"


@pytest.mark.usefixtures("running")
def test_reload_prints_the_supervisors_report_as_json_and_exits_zero(
    config: Path, supervisor: FakeSupervisor, capsys: pytest.CaptureFixture[str]
) -> None:
    assert control.main(["--config", str(config)]) == 0

    assert json.loads(capsys.readouterr().out) == REPORT
    assert supervisor.reloads == 1
    assert not supervisor.reexecuted


@pytest.mark.usefixtures("running")
def test_a_report_of_re_execution_is_sent_before_the_supervisor_re_executes(
    config: Path, supervisor: FakeSupervisor, capsys: pytest.CaptureFixture[str]
) -> None:
    supervisor.report = {"supervisor": "re-executed", "children": {"pulls": "replaced"}}

    assert control.main(["--config", str(config)]) == 0

    assert json.loads(capsys.readouterr().out) == supervisor.report
    deadline = 50
    while not supervisor.reexecuted and deadline:
        deadline -= 1
        time.sleep(0.1)
    assert supervisor.reexecuted


def test_with_no_supervisor_running_reload_says_so_and_exits_one(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert control.main(["--config", str(config)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no supervisor is running" in captured.err
    assert str(control.control_file(config)) in captured.err


def test_a_control_file_nothing_listens_on_is_no_supervisor_either(
    config: Path, running: Control, capsys: pytest.CaptureFixture[str]
) -> None:
    file = control.control_file(config)
    stale = file.read_text()
    running.stop()
    file.write_text(stale)

    assert control.main(["--config", str(config)]) == 1

    assert "no supervisor is running" in capsys.readouterr().err


@pytest.mark.usefixtures("running")
def test_a_reload_that_fails_exits_two_with_the_reason_and_the_supervisor_keeps_running(
    config: Path, supervisor: FakeSupervisor, capsys: pytest.CaptureFixture[str]
) -> None:
    supervisor.failure = ReloadError("starpulse._internal.server.worker does not import")

    assert control.main(["--config", str(config)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "does not import" in captured.err
    assert not supervisor.reexecuted


def test_a_request_without_the_token_is_refused_and_reloads_nothing(
    config: Path, supervisor: FakeSupervisor, running: Control
) -> None:
    port = json.loads(control.control_file(config).read_text())["port"]
    request = urllib.request.Request(f"http://127.0.0.1:{port}/reload", method="POST")

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)

    assert refused.value.code == 401
    assert supervisor.reloads == 0


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")
def test_the_control_file_holds_the_token_and_only_its_owner_can_read_it(config: Path, running: Control) -> None:
    assert control.control_file(config).stat().st_mode & 0o777 == 0o600


def test_stopping_removes_the_control_file(config: Path, running: Control) -> None:
    running.stop()

    assert not control.control_file(config).exists()


def test_stopping_returns_well_inside_the_default_half_second_poll(config: Path, running: Control) -> None:
    """`shutdown` waits out the serving loop's poll; every supervisor stop and every test that starts one pays it."""
    started = time.monotonic()
    running.stop()

    assert time.monotonic() - started < 0.25
