"""`starpulse command run`: one named project command, offline, with its placeholders filled."""

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.cli import agent_cli as cli


def _run(capsys: pytest.CaptureFixture[str], tmp_path: Path, toml: str, argv: Sequence[str]) -> tuple[int, Any]:
    config = tmp_path / "starpulse.toml"
    config.write_text(toml)
    code = cli.main(["command", "run", "--config", str(config), *argv], {})
    return code, json.loads(capsys.readouterr().out)


def _table(argv: list[str]) -> str:
    return f"[project.commands]\ngo = {json.dumps(argv)}\n"


def test_a_succeeding_command_exits_0_and_reports_its_argv(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, document = _run(capsys, tmp_path, _table([sys.executable, "-c", "pass"]), ["go"])

    assert code == 0
    assert (document["name"], document["argv"], document["exit"]) == ("go", [sys.executable, "-c", "pass"], 0)
    assert document["seconds"] >= 0


def test_placeholders_are_filled_and_args_are_spliced(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    script = f"import sys, pathlib; pathlib.Path({str(out)!r}).write_text(repr(sys.argv[1:]))"
    argv = [sys.executable, "-c", script, "{task}", "{kind}", "{args}"]

    code, _ = _run(capsys, tmp_path, _table(argv), ["go", "--task", "T-1", "--arg", "kind=fix", "--", "a", "b"])

    assert code == 0
    assert out.read_text() == "['T-1', 'fix', 'a', 'b']"


def test_a_failing_child_exits_1_with_its_code(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, document = _run(capsys, tmp_path, _table([sys.executable, "-c", "raise SystemExit(7)"]), ["go"])

    assert (code, document["exit"]) == (1, 7)


def test_a_placeholder_without_a_value_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, document = _run(capsys, tmp_path, _table(["echo", "{task}"]), ["go"])

    assert code == 2
    assert document["code"] == "usage"
    assert "{task}" in document["error"]


def test_a_program_that_cannot_run_exits_3(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, document = _run(capsys, tmp_path, _table(["./no-such-program"]), ["go"])

    assert (code, document["code"]) == (3, "unavailable")


def test_an_unknown_name_exits_4_naming_the_fallback(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, document = _run(capsys, tmp_path, _table(["true"]), ["deliver"])

    assert code == 4
    assert document["code"] == "not_found"
    assert document["fallback"] == "AGENTS.md"
