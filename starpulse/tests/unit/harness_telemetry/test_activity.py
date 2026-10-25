"""A tool call lifted to activities: a closed vocabulary that carries no argument, so a trace recurs across sessions."""

import pytest

from starpulse.harness_telemetry.activity import activities, paths, writes_file


def shell(command: str) -> list[str]:
    return activities("Bash", {"command": command})


def test_a_non_shell_tool_is_its_bare_name() -> None:
    assert activities("Read", {"file_path": "/r/a.py"}) == ["Read"]
    assert activities("mcp__board__create_task", {}) == ["create_task"]


def test_a_shell_call_whose_export_carries_no_command_is_its_tool_name() -> None:
    assert activities("Bash", {}) == ["Bash"]
    assert activities("exec_command", {"cmd": ""}) == ["exec_command"]


def test_a_tool_whose_name_is_not_a_name_is_tool_other() -> None:
    assert activities("cat a | grep b", {}) == ["tool_other"]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git -C /r status && gh pr view 12 --json title", ["git status", "gh pr view"]),
        ("git worktree add ../x && git log", ["git worktree add", "git log"]),
        ("make lint-changed", ["make lint-changed"]),
        ("bin/obs.py query 'up' | head -3", ["bin/obs.py"]),
        ("/r/.claude/worktrees/t/bin/obs.py query", ["bin/obs.py"]),
        ("FOO=1 timeout 30 uv run bin/check.sh --all", ["bin/check.sh"]),
        ("timeout -s KILL 5 make test", ["make test"]),
        ("timeout --signal=KILL --kill-after 2 5 make test", ["make test"]),
        ("nice -n 10 make test", ["make test"]),
        ("env -u FOO git status", ["git status"]),
        ("uv run --project starpulse pytest -q", ["pytest"]),
        ("uv run --directory /r/starpulse pytest -q", ["pytest"]),
        ("uv run --project=starpulse pytest -q", ["pytest"]),
        ("ssh -p 22 -i key root@unraid 'docker ps'", ["ssh root@unraid"]),
        ("docker ps; psql -c 'select 1'", ["docker", "psql"]),
        ("cat a.txt | grep b; ls -la", ["shell_read", "shell_search"]),
        ("sed -i s/a/b/ f.txt", ["shell_other"]),
        ("cd /r && echo hi && sleep 1", []),
        ("for f in *.md; do make fmt; done", ["make fmt"]),
        ("cat <<EOF\ngit push\nEOF", ["shell_read"]),
    ],
)
def test_a_shell_call_is_each_statements_leading_command(command: str, expected: list[str]) -> None:
    assert shell(command) == expected


def test_a_file_tool_names_the_path_it_reads_or_writes() -> None:
    assert paths("Read", {"file_path": "/r/a.py"}, "") == (["/r/a.py"], [])
    assert paths("Grep", {"pattern": "x", "path": "/r/lib"}, "") == (["/r/lib"], [])
    assert paths("Edit", {"file_path": "/r/b.py"}, "") == ([], ["/r/b.py"])
    assert paths("NotebookEdit", {"notebook_path": "/r/n.ipynb"}, "") == ([], ["/r/n.ipynb"])


def test_apply_patch_writes_the_files_its_headers_name() -> None:
    patch = "*** Begin Patch\n*** Update File: lib/a.py\n@@\n-x\n*** Add File: docs/b.md\n*** End Patch"

    assert paths("apply_patch", {}, patch) == ([], ["lib/a.py", "docs/b.md"])


def test_a_shell_call_and_a_pathless_tool_name_no_path() -> None:
    assert paths("Bash", {"command": "cat /r/a.py"}, "") == ([], [])
    assert paths("Read", {}, "") == ([], [])


@pytest.mark.parametrize(
    "command",
    [
        # A quote that never closes runs to the end of the command, so its SQL and Python are one argument.
        'psql -c "select 1\nFROM t\nWHERE x AS y"',
        'psql -c "select DISTINCT a\nfrom t',
        "python3 -c 'import json\nfrom os import path",
        # A loop's `break` and `continue` are syntax, like `done`.
        "for f in a b; do break; done",
        "while true; do continue; done",
    ],
)
def test_sql_python_and_shell_syntax_are_not_activities(command: str) -> None:
    assert shell(command) in ([], ["psql"], ["shell_other"])
    assert not {"from", "FROM", "AS", "DISTINCT", "break", "continue", "import"} & set(shell(command))


def test_a_loop_body_keeps_its_commands_past_break() -> None:
    assert shell("for f in a b; do make test; break; done") == ["make test"]


@pytest.mark.parametrize(
    "command",
    [
        "echo x > notes.txt",
        "cat <<'EOF' > a.py\n[heredoc length=3 sha256=ab]\nEOF",
        "cat > a.py <<EOF\n[heredoc length=3 sha256=ab]\nEOF",
        "printf x >> log.txt && ls",
        "python3 - <<'EOF'\n[heredoc length=53 sha256=ab]\nEOF",
        "sed -i 's/a/b/' a.py",
        "git apply fix.patch",
        "patch -p1 < fix.patch",
        "ls | tee out.txt",
    ],
)
def test_a_shell_command_that_writes_a_file_is_a_write(command: str) -> None:
    assert writes_file(command)


@pytest.mark.parametrize(
    "command",
    [
        "ls -l && git status",
        "make test 2>&1 | tail -5",
        "pytest > /dev/null 2>/dev/null",
        "rg foo 2>&1",
        "cat <<'EOF' | wc -l\n[heredoc length=3 sha256=ab]\nEOF",
        "sed -n 1,5p a.py",
    ],
)
def test_a_shell_command_that_only_reads_is_not_a_write(command: str) -> None:
    assert not writes_file(command)
