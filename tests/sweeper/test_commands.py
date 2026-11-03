"""A kind or housekeeping step a project declares as a command in its StarPulse config."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starpulse.sweeper.commands import CommandHousekeeping, CommandKind
from starpulse.sweeper.config import Sweeper, SweeperError, parse_sweeper


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_a_command_kind_reports_the_count_it_prints(tmp_path: Path) -> None:
    kind = CommandKind("sessions", _python('print("noise"); print(\'{"corrected": 3, "sampled": 8}\')'), tmp_path, 30)

    outcome = kind.run()

    assert (kind.name, outcome.corrected, outcome.sampled) == ("sessions", 3, 8)


def test_a_command_kind_reports_a_bare_count(tmp_path: Path) -> None:
    outcome = CommandKind("sessions", _python("print(4)"), tmp_path, 30).run()

    assert (outcome.corrected, outcome.sampled) == (4, 0)


def test_the_config_loader_reads_the_sweeper_table(tmp_path: Path) -> None:
    from starpulse.runtime.config import load

    path = tmp_path / "starpulse.toml"
    path.write_text('[sweeper]\ninterval_s = 60\n\n[[sweeper.kinds]]\nname = "sessions"\ncommand = ["true"]\n')

    sweeper = load(path).sweeper

    assert (sweeper.interval_s, [kind.name for kind in sweeper.kinds]) == (60, ["sessions"])


@pytest.mark.parametrize(
    "code", ["import sys; sys.exit(2)", 'print("not json")', 'print(\'{"fixed": 1}\')', "print('{\"corrected\": -1}')"]
)
def test_a_command_that_fails_or_prints_no_count_raises(tmp_path: Path, code: str) -> None:
    with pytest.raises(RuntimeError, match="sessions"):
        CommandKind("sessions", _python(code), tmp_path, 30).run()


def test_a_command_runs_in_the_base_directory(tmp_path: Path) -> None:
    kind = CommandKind("here", _python('import os, json; print(json.dumps({"corrected": int(os.getcwd() == %r)}))' % str(tmp_path)), tmp_path, 30)

    assert kind.run().corrected == 1


def test_housekeeping_runs_its_command_and_a_failure_raises(tmp_path: Path) -> None:
    CommandHousekeeping("ok", _python("pass"), tmp_path, 30).run()

    with pytest.raises(RuntimeError, match="lint"):
        CommandHousekeeping("lint", _python("import sys; sys.exit(1)"), tmp_path, 30).run()


def test_the_sweeper_table_defaults_to_an_hourly_pass_and_no_commands() -> None:
    assert parse_sweeper(None) == Sweeper()
    assert Sweeper().interval_s == 3600


def test_the_sweeper_table_declares_kinds_and_housekeeping_as_commands() -> None:
    table = {
        "interval_s": 600,
        "kinds": [{"name": "sessions", "command": ["bin/sessions"], "timeout_s": 60}],
        "housekeeping": [{"name": "sweep", "command": ["backlog-task", "sweep"]}],
    }

    sweeper = parse_sweeper(table)

    assert sweeper.interval_s == 600
    assert [(k.name, k.command, k.timeout_s) for k in sweeper.kinds] == [("sessions", ["bin/sessions"], 60)]
    assert [(h.name, h.command) for h in sweeper.housekeeping] == [("sweep", ["backlog-task", "sweep"])]


@pytest.mark.parametrize(
    "table",
    [
        {"interval_s": 0},
        {"interval_s": "hourly"},
        {"kinds": [{"name": "x"}]},
        {"kinds": [{"name": "x", "command": []}]},
        {"kinds": [{"name": "x", "command": ["a"]}, {"name": "x", "command": ["b"]}]},
        {"kinds": [{"name": "readers", "command": ["a"]}]},
        {"surprise": 1},
    ],
)
def test_a_sweeper_table_the_sweeper_cannot_run_is_refused(table: dict) -> None:
    with pytest.raises(SweeperError):
        parse_sweeper(table)
