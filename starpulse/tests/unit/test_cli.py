"""`starpulse serve|emit`: the installed command names each subcommand and hands it the rest of the line."""

from importlib.metadata import entry_points

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


def test_no_subcommand_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main([])

    assert exited.value.code == 2
    assert "serve" in capsys.readouterr().err
