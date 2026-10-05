"""The installed `starpulse` command: `serve` and `emit` get the rest of the line, any other word is an agent verb."""

import json
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from starpulse import __main__ as cli


def test_the_installed_starpulse_command_is_this_module() -> None:
    (script,) = entry_points(group="console_scripts", name="starpulse")

    assert script.load() is cli.main


def test_help_names_both_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["--help"])

    assert exited.value.code == 0
    out = capsys.readouterr().out
    assert "serve" in out and "emit" in out


@pytest.mark.parametrize("command", ["serve", "emit"])
def test_a_subcommand_gets_the_rest_of_the_line(monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    seen: list[list[str]] = []
    monkeypatch.setitem(cli.COMMANDS, command, lambda argv: seen.append(argv) or 3)

    assert cli.main([command, "--port", "1"]) == 3
    assert seen == [["--port", "1"]]


def test_an_agent_verb_runs_through_the_installed_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["help", "--agent"]) == 0

    assert "snapshot" in {v["verb"] for v in json.loads(capsys.readouterr().out)["verbs"]}


def test_the_command_line_the_shell_gave_is_what_runs_when_no_argv_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setitem(cli.COMMANDS, "serve", lambda argv: seen.append(argv) or 3)
    monkeypatch.setattr("sys.argv", ["starpulse", "serve", "--port", "1"])

    assert cli.main() == 3
    assert seen == [["--port", "1"]]


def test_no_subcommand_is_a_usage_error_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2

    assert json.loads(capsys.readouterr().out)["code"] == "usage"


def test_the_offline_verbs_are_in_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["help", "--agent"]) == 0

    verbs = {v["verb"] for v in json.loads(capsys.readouterr().out)["verbs"]}
    assert {"machine validate", "machine import mermaid", "config check", "demo"} <= verbs


def test_machine_import_mermaid_runs_through_the_installed_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, out = tmp_path / "flow.mmd", tmp_path / "flow.yaml"
    source.write_text("stateDiagram-v2\n    [*] --> open\n    open --> closed : Close it\n")

    assert cli.main(["machine", "import", "mermaid", str(source), "--out", str(out)]) == 0

    assert json.loads(capsys.readouterr().out) == {"written": str(out)}
    assert "CLOSE_IT" in out.read_text()


def test_demo_runs_through_the_installed_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    design, out = tmp_path / "design", tmp_path / "demo.html"
    design.mkdir()
    board = {"agents": [{"id": "PROJ-1", "title": "Rotate the secret", "state": "ready"}]}
    snap = {"now": 1.0, "dags": [], "flows": {"board": board, "in-progress": {"agents": []}}}
    (design / "data.js").write_text(f"window.SNAP = {json.dumps(snap)};\n")
    (design / "index.html").write_text('<script src="data.js"></script>')

    assert cli.main(["demo", "--mockup", str(design), "--out", str(out)]) == 0

    assert json.loads(capsys.readouterr().out) == {"written": str(out)}
    assert "DEMO-1" in out.read_text()
