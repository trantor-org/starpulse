"""A tool call lifted to activities: a closed vocabulary that carries no argument, so a trace recurs across sessions."""

import pytest

from starpulse._internal.harnesses.activity import activities, paths


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
