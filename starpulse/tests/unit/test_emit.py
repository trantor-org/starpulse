"""`starpulse emit`: the push path onto the event log."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, get_args

import pytest

from starpulse._internal.adapters.runs import emit
from starpulse.contracts.adapters import RunStatus
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import DEFAULT_FILE

NOW = 1_700_000_000.0


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def run(*argv: str, log: EventLog) -> int:
    return emit.main(list(argv), now=lambda: NOW, log=log)


def appended(log: EventLog) -> list[dict[str, Any]]:
    return [entry.fields for entry in Tail(log, "runs:events").poll()]


def test_a_run_start_becomes_one_entry_with_the_flags_it_was_given(log: EventLog) -> None:
    code = run("start", "--workflow", "nightly", "--run", "r1", "--status", "running", log=log)

    assert code == 0
    assert appended(log) == [
        {"time": NOW, "phase": "start", "workflow": "nightly", "run_id": "r1", "status": "running"}
    ]


def test_a_step_entry_carries_its_name_and_the_steps_it_depends_on(log: EventLog) -> None:
    run(
        "end", "--workflow", "nightly", "--run", "r1", "--status", "succeeded",
        "--step", "load", "--depends", "fetch,clean",
        log=log,
    )  # fmt: skip

    assert appended(log) == [
        {
            "time": NOW,
            "phase": "end",
            "workflow": "nightly",
            "run_id": "r1",
            "status": "succeeded",
            "step": "load",
            "depends": ["fetch", "clean"],
        }
    ]


@pytest.mark.parametrize("status", ["done", "SUCCESS", "waiting", ""])
def test_a_status_outside_the_contract_is_refused_naming_the_allowed_values(
    status: str, log: EventLog, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        run("end", "--workflow", "w", "--run", "r", "--status", status, log=log)

    assert refused.value.code != 0
    error = capsys.readouterr().err
    for allowed in get_args(RunStatus):
        assert allowed in error
    assert appended(log) == []


def test_depends_without_a_step_is_refused(log: EventLog, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        run("start", "--workflow", "w", "--run", "r", "--status", "running", "--depends", "a", log=log)

    assert refused.value.code != 0
    assert "error: --depends needs --step" in capsys.readouterr().err


def test_a_store_that_refuses_the_entry_exits_one_so_the_caller_can_tell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unreachable = EventLog(f"sqlite:///{tmp_path / 'missing-directory' / 'events.sqlite'}")

    code = run("start", "--workflow", "w", "--run", "r", "--status", "running", log=unreachable)

    assert code == 1
    assert "runs:events" in capsys.readouterr().err


def test_config_names_the_database_the_entry_is_appended_to(tmp_path: Path) -> None:
    config = tmp_path / "view.toml"
    config.write_text(f'database_url = "sqlite:///{tmp_path / "chosen.sqlite"}"\n')

    code = emit.main(["start", "--workflow", "w", "--run", "r", "--status", "running", "--config", str(config)])

    assert code == 0
    assert [
        e.fields["workflow"] for e in Tail(EventLog(f"sqlite:///{tmp_path / 'chosen.sqlite'}"), "runs:events").poll()
    ] == ["w"]


def test_a_config_without_a_database_url_appends_to_the_history_file_beside_it(tmp_path: Path) -> None:
    config = tmp_path / "view.toml"
    config.write_text('tracker_url = "http://tracker"\n')

    emit.main(["start", "--workflow", "w", "--run", "r", "--status", "running", "--config", str(config)])

    assert [
        e.fields["run_id"] for e in Tail(EventLog(f"sqlite:///{tmp_path / DEFAULT_FILE}"), "runs:events").poll()
    ] == ["r"]


def test_without_a_config_flag_the_starpulse_toml_in_the_working_directory_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "starpulse.toml").write_text(f'database_url = "sqlite:///{tmp_path / "found.sqlite"}"\n')
    monkeypatch.chdir(tmp_path)

    emit.main(["start", "--workflow", "w", "--run", "r", "--status", "running"])

    assert [
        e.fields["workflow"] for e in Tail(EventLog(f"sqlite:///{tmp_path / 'found.sqlite'}"), "runs:events").poll()
    ] == ["w"]


def test_without_any_config_the_entry_goes_to_the_history_file_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    emit.main(["start", "--workflow", "w", "--run", "r", "--status", "running"])

    assert [
        e.fields["workflow"] for e in Tail(EventLog(f"sqlite:///{tmp_path / DEFAULT_FILE}"), "runs:events").poll()
    ] == ["w"]


def test_a_config_that_cannot_be_read_is_a_usage_error_and_appends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "view.toml"
    config.write_text("mode = [\n")

    with pytest.raises(SystemExit) as refused:
        emit.main(["start", "--workflow", "w", "--run", "r", "--status", "running", "--config", str(config)])

    assert refused.value.code == 2
    assert str(config) in capsys.readouterr().err
    assert not (tmp_path / DEFAULT_FILE).exists()


def test_the_command_line_refuses_a_bad_status_with_a_usage_error_naming_the_allowed_values() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "starpulse", "emit", "end", "--workflow", "w", "--run", "r", "--status", "done"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 2
    assert all(allowed in result.stderr for allowed in get_args(RunStatus))


def test_the_help_names_the_command_and_each_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as helped:
        emit.main(["--help"])

    assert helped.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for expected in (
        "usage: starpulse emit",
        "{start,end}",
        "push a workflow run, or one of its steps, onto the event log",
        "the TOML config whose database holds the event log",
        "the run's id",
        "report this step of the run instead of the run itself",
        "comma-separated names of the steps it waits on",
    ):
        assert expected in text


@pytest.mark.parametrize("missing", ["--workflow", "--run", "--status"])
def test_a_missing_required_flag_is_a_usage_error(
    missing: str, log: EventLog, capsys: pytest.CaptureFixture[str]
) -> None:
    flags = {"--workflow": "w", "--run": "r", "--status": "running"}
    argv = [part for flag, value in flags.items() if flag != missing for part in (flag, value)]

    with pytest.raises(SystemExit) as refused:
        run("start", *argv, log=log)

    assert refused.value.code == 2
    assert f"required: {missing}" in capsys.readouterr().err


def test_a_phase_other_than_start_or_end_is_refused(log: EventLog, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        run("pause", "--workflow", "w", "--run", "r", "--status", "running", log=log)

    assert refused.value.code == 2
    assert "invalid choice: 'pause'" in capsys.readouterr().err
