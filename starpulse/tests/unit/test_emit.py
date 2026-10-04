"""`starpulse emit`: the push path onto the runs stream."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, get_args

import pytest

from starpulse import emit
from starpulse.contracts import RunStatus

NOW = 1_700_000_000.0


class Producer:
    """Stands in for `StreamProducer`: keeps what was emitted, or refuses like a Redis that is down."""

    def __init__(self, entry_id: str | None = "1-0") -> None:
        self.entry_id = entry_id
        self.entries: list[dict[str, Any]] = []

    def emit(self, fields: dict[str, Any]) -> str | None:
        self.entries.append(fields)
        return self.entry_id


def run(*argv: str, producer: Producer | None = None, environ: dict[str, str] | None = None) -> int:
    return emit.main(list(argv), environ or {}, now=lambda: NOW, producer=producer or Producer())


def test_a_run_start_becomes_one_entry_with_the_flags_it_was_given() -> None:
    producer = Producer()

    code = run("start", "--workflow", "nightly", "--run", "r1", "--status", "running", producer=producer)

    assert code == 0
    assert producer.entries == [
        {"time": NOW, "phase": "start", "workflow": "nightly", "run_id": "r1", "status": "running"}
    ]


def test_a_step_entry_carries_its_name_and_the_steps_it_depends_on() -> None:
    producer = Producer()

    run(
        "end", "--workflow", "nightly", "--run", "r1", "--status", "succeeded",
        "--step", "load", "--depends", "fetch,clean",
        producer=producer,
    )  # fmt: skip

    assert producer.entries[0] | {"time": 0} == {
        "time": 0,
        "phase": "end",
        "workflow": "nightly",
        "run_id": "r1",
        "status": "succeeded",
        "step": "load",
        "depends": ["fetch", "clean"],
    }


@pytest.mark.parametrize("status", ["done", "SUCCESS", "waiting", ""])
def test_a_status_outside_the_contract_is_refused_naming_the_allowed_values(
    status: str, capsys: pytest.CaptureFixture[str]
) -> None:
    producer = Producer()

    with pytest.raises(SystemExit) as refused:
        run("end", "--workflow", "w", "--run", "r", "--status", status, producer=producer)

    assert refused.value.code != 0
    error = capsys.readouterr().err
    for allowed in get_args(RunStatus):
        assert allowed in error
    assert producer.entries == []


def test_depends_without_a_step_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        run("start", "--workflow", "w", "--run", "r", "--status", "running", "--depends", "a")

    assert refused.value.code != 0
    assert "error: --depends needs --step" in capsys.readouterr().err


def test_a_stream_that_refuses_the_entry_exits_non_zero_so_the_caller_can_tell(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run("start", "--workflow", "w", "--run", "r", "--status", "running", producer=Producer(entry_id=None))

    assert code == 1
    assert "runs:events" in capsys.readouterr().err


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
        run("--help")

    assert helped.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for expected in (
        "usage: starpulse emit",
        "{start,end}",
        "push a workflow run, or one of its steps, onto the runs stream",
        "the run's id",
        "report this step of the run instead of the run itself",
        "comma-separated names of the steps it waits on",
    ):
        assert expected in text


@pytest.mark.parametrize("missing", ["--workflow", "--run", "--status"])
def test_a_missing_required_flag_is_a_usage_error(missing: str, capsys: pytest.CaptureFixture[str]) -> None:
    flags = {"--workflow": "w", "--run": "r", "--status": "running"}
    argv = [part for flag, value in flags.items() if flag != missing for part in (flag, value)]

    with pytest.raises(SystemExit) as refused:
        run("start", *argv)

    assert refused.value.code == 2
    assert f"required: {missing}" in capsys.readouterr().err


def test_a_phase_other_than_start_or_end_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        run("pause", "--workflow", "w", "--run", "r", "--status", "running")

    assert refused.value.code == 2
    assert "invalid choice: 'pause'" in capsys.readouterr().err


def test_without_an_injected_producer_the_redis_the_environment_names_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached: list[Any] = []
    producer = Producer()
    monkeypatch.setattr(emit.run_events, "producer", lambda environ: reached.append(environ) or producer)
    environ = {"REDIS_URL": "redis://cache.lan"}

    code = emit.main(["start", "--workflow", "w", "--run", "r", "--status", "running"], environ, now=lambda: NOW)

    assert code == 0
    assert reached == [environ]
    assert len(producer.entries) == 1
