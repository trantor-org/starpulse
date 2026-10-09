"""`starpulse connect native|backlog|jira`: check the tracker answers, then write `[board]` into starpulse.toml."""

from pathlib import Path

import pytest
import tomllib

from starpulse._internal.cli import agent_cli, connect
from starpulse._internal.config.config import load
from starpulse.tests.integration.test_jira import WORKFLOW, recorded_site, serve

OTHER_TABLES = '# the hub this instance reports to\ntracker_url = "https://tracker.example"\n\n[[runs]]\nname = "prod"\ntype = "dagu"\nurl = "http://dagu:8080"\n'


def backlog_project(
    root: Path, tasks: int, statuses: tuple[str, ...] = ("To Do", "Doing", "Review", "Blocked", "Done")
) -> None:
    (root / "tasks").mkdir(parents=True)
    lanes = "".join(f"  - {status}\n" for status in statuses)
    (root / "config.yml").write_text(f"project_name: Launch\ntask_prefix: task\nstatuses:\n{lanes}")
    for n in range(1, tasks + 1):
        (root / "tasks" / f"task-{n} - t.md").write_text(
            f"---\nid: task-{n}\ntitle: Task {n}\nstatus: To Do\n---\n\nBody\n"
        )


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def board_of(path: Path) -> dict:
    return tomllib.loads(path.read_text())["board"]


def test_connect_backlog_writes_the_board_table_config_check_accepts_and_says_what_it_read(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backlog_project(workdir / "backlog", 3)

    assert connect.main(["backlog", "--path", "backlog"]) == 0

    assert capsys.readouterr().out == "✓ Read 3 tasks in 5 lanes from backlog/ · wrote [board] to starpulse.toml\n"
    assert board_of(workdir / "starpulse.toml") == {"type": "upstream_backlog", "path": "backlog"}
    assert agent_cli.main(["config", "check"]) == 0
    assert load(workdir / "starpulse.toml").board_type == "upstream_backlog"


def test_connect_backlog_keeps_the_command_that_writes_moves(workdir: Path) -> None:
    backlog_project(workdir / "backlog", 1)

    assert connect.main(["backlog", "--path", "backlog", "--command", "npx backlog"]) == 0

    assert board_of(workdir / "starpulse.toml") == {
        "type": "upstream_backlog",
        "path": "backlog",
        "command": "npx backlog",
    }


def test_connect_native_creates_the_default_board_and_writes_the_table(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert connect.main(["native"]) == 0

    assert (
        capsys.readouterr().out
        == "✓ Read 0 tasks in 3 lanes from .starpulse/board/ · wrote [board] to starpulse.toml\n"
    )
    assert board_of(workdir / "starpulse.toml") == {"type": "native", "path": ".starpulse/board"}
    assert agent_cli.main(["config", "check"]) == 0


MACHINE = """\
name: board
states:
  to_do: {initial: true}
  in_progress: {}
  done: {final: true}
events:
  to_in_progress: [{from: to_do, to: in_progress}]
  to_done: [{from: in_progress, to: done}]
"""


def test_connect_native_reads_a_board_kept_elsewhere_and_writes_its_machine_file(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backlog_project(workdir / "work" / "board", 2, ("To Do", "In Progress", "Done"))
    (workdir / "board.yaml").write_text(MACHINE)

    assert connect.main(["native", "--path", "work/board", "--machine", "board.yaml"]) == 0

    assert capsys.readouterr().out == "✓ Read 2 tasks in 3 lanes from work/board/ · wrote [board] to starpulse.toml\n"
    assert board_of(workdir / "starpulse.toml") == {"type": "native", "path": "work/board", "machine": "board.yaml"}


def test_connect_native_refuses_a_machine_whose_states_are_not_the_boards_lanes(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backlog_project(workdir / "work" / "board", 1, ("To Do", "Doing", "Done"))
    (workdir / "board.yaml").write_text(MACHINE)

    assert connect.main(["native", "--path", "work/board", "--machine", "board.yaml"]) == 1

    assert "disagree on lanes" in capsys.readouterr().err
    assert not (workdir / "starpulse.toml").exists()


def test_connect_replaces_the_board_table_and_keeps_every_other_table_and_comment(workdir: Path) -> None:
    config = workdir / "starpulse.toml"
    config.write_text(
        f'{OTHER_TABLES}\n[board]\ntype = "native"\npath = "old"\n\n# where events go\n[forward]\nurl = "https://hub.example"\ntoken_env = "HUB_TOKEN"\n'
    )
    backlog_project(workdir / "backlog", 1)

    assert connect.main(["backlog", "--path", "backlog"]) == 0

    text = config.read_text()
    assert text.startswith("# the hub this instance reports to\n")
    parsed = tomllib.loads(text)
    assert parsed["board"] == {"type": "upstream_backlog", "path": "backlog"}
    assert parsed["tracker_url"] == "https://tracker.example"
    assert parsed["runs"] == [{"name": "prod", "type": "dagu", "url": "http://dagu:8080"}]
    assert parsed["forward"] == {"url": "https://hub.example", "token_env": "HUB_TOKEN"}
    assert "# where events go\n[forward]" in text
    assert text.count("[board]") == 1


def test_connect_appends_the_board_table_to_a_config_without_one(workdir: Path) -> None:
    config = workdir / "starpulse.toml"
    config.write_text(OTHER_TABLES)
    backlog_project(workdir / "backlog", 1)

    assert connect.main(["backlog", "--path", "backlog"]) == 0

    assert config.read_text().startswith(OTHER_TABLES)
    assert board_of(config) == {"type": "upstream_backlog", "path": "backlog"}


def test_connect_writes_where_config_says(workdir: Path) -> None:
    backlog_project(workdir / "backlog", 1)

    assert connect.main(["backlog", "--path", "backlog", "--config", "elsewhere.toml"]) == 0

    assert board_of(workdir / "elsewhere.toml")["path"] == "backlog"
    assert not (workdir / "starpulse.toml").exists()


def test_connect_jira_writes_the_jira_table_with_the_token_variable_and_never_the_token(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JIRA_TOKEN", "s3cret-token-value")

    with serve(recorded_site()) as url:
        code = connect.main(
            ["jira", "--url", url, "--project", "PAY", "--workflow", WORKFLOW, "--user", "ada@example.com"]
        )

    assert code == 0
    assert capsys.readouterr().out == (
        f"✓ Imported {WORKFLOW} (4 states) · read 4 issues from PAY · wrote [board] to starpulse.toml\n"
    )
    config = workdir / "starpulse.toml"
    assert board_of(config) == {
        "type": "jira",
        "url": url,
        "project": "PAY",
        "workflow": WORKFLOW,
        "token_env": "JIRA_TOKEN",
        "user": "ada@example.com",
    }
    assert "s3cret-token-value" not in config.read_text()
    assert agent_cli.main(["config", "check"]) == 0


def test_jira_takes_no_token_flag(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        connect.main(["jira", "--url", "http://x", "--project", "P", "--workflow", "w", "--token", "abc"])

    assert exited.value.code == 2
    assert not (workdir / "starpulse.toml").exists()


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["backlog", "--path", "missing"], "missing"),
        (["backlog", "--path", "nameless"], "project_name"),
        (
            ["jira", "--url", "http://127.0.0.1:9", "--project", "PAY", "--workflow", "w"],
            "jira site http://127.0.0.1:9",
        ),
        (
            ["jira", "--url", "http://127.0.0.1:9", "--project", "PAY", "--workflow", "w", "--token-env", "X"],
            "unrecognized",
        ),
    ],
)
def test_a_tracker_that_does_not_answer_leaves_the_config_unchanged_and_exits_nonzero_with_the_reason(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, argv: list[str], reason: str
) -> None:
    monkeypatch.setenv("JIRA_TOKEN", "s3cret")
    (workdir / "nameless" / "tasks").mkdir(parents=True)
    (workdir / "nameless" / "config.yml").write_text("task_prefix: task\n")
    config = workdir / "starpulse.toml"
    config.write_text(OTHER_TABLES)

    try:
        code = connect.main(argv)
    except SystemExit as exited:
        code = int(exited.code or 0)

    assert code != 0
    assert reason in capsys.readouterr().err
    assert config.read_text() == OTHER_TABLES
    assert sorted(p.name for p in workdir.iterdir() if p.is_file()) == ["starpulse.toml"]


def test_a_missing_token_is_refused_naming_the_variable(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JIRA_TOKEN", raising=False)

    assert connect.main(["jira", "--url", "http://x", "--project", "PAY", "--workflow", "w"]) == 1

    assert "$JIRA_TOKEN holds no Jira token" in capsys.readouterr().err
    assert not (workdir / "starpulse.toml").exists()


def test_a_board_table_that_cannot_be_replaced_cleanly_is_refused(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = workdir / "starpulse.toml"
    config.write_text('board = { type = "native" }\n')
    backlog_project(workdir / "backlog", 1)

    assert connect.main(["backlog", "--path", "backlog"]) == 1

    assert config.read_text() == 'board = { type = "native" }\n'
    assert "[board]" in capsys.readouterr().err


def test_a_config_that_is_not_toml_is_refused_and_left_alone(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = workdir / "starpulse.toml"
    config.write_text("this is = = not toml")
    backlog_project(workdir / "backlog", 1)

    assert connect.main(["backlog", "--path", "backlog"]) == 1

    assert config.read_text() == "this is = = not toml"
    assert "starpulse.toml" in capsys.readouterr().err


@pytest.mark.parametrize("adapter", ["native", "backlog", "jira"])
def test_each_adapter_lists_its_flags_under_help(capsys: pytest.CaptureFixture[str], adapter: str) -> None:
    with pytest.raises(SystemExit) as exited:
        connect.main([adapter, "--help"])

    assert exited.value.code == 0
    out = capsys.readouterr().out
    flags = {
        "native": ["--path", "--machine"],
        "backlog": ["--path", "--command"],
        "jira": ["--url", "--project", "--workflow", "--user"],
    }
    assert all(flag in out for flag in flags[adapter])
    assert adapter != "jira" or "JIRA_TOKEN" in out
