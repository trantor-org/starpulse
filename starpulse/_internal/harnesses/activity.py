"""What one tool call did, lifted to activities with no arguments so a trace recurs across sessions.

A non-shell tool is its bare name (an MCP tool's, past its server prefix). A shell call is split into statements, and
each statement's leading command (the head of a pipeline, past env assignments and wrappers such as `uv run` or
`timeout`) becomes one activity:

- `bin/<script>`, a repository entry point
- `make <target>`, `git <subcommand>` or `gh <group> <verb>`
- `ssh <host>`
- `shell_read` or `shell_search` for a file read or a search
- the command's own name for any other command, or `shell_other` when it is not a name

Shell keywords are syntax, not commands: `do make test` is `make test`, and a statement that is only a keyword
(`done`, `for f in ...`) or an output-only builtin (`cd`, `echo`, `sleep`) takes no activity. A tool name that is not a
name (a model once named a tool with a shell pipeline) is `tool_other`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ["SHELLS", "activities", "elide_heredocs", "paths"]

#: The tools that run a shell command, whose input is a command line.
SHELLS = frozenset({"Bash", "exec_command", "shell", "local_shell"})

SHELL_READ = "shell_read"
SHELL_SEARCH = "shell_search"
SHELL_OTHER = "shell_other"
TOOL_OTHER = "tool_other"

# A heredoc: its `<<TAG` line, its body, and the line that ends it (the end of the command when unterminated, which
# a shell accepts).
_HEREDOC = re.compile(
    r"(?P<head><<-?[ \t]*(?P<quote>['\"]?)(?P<tag>\w+)(?P=quote)[^\n]*\n)(?P<body>.*?)(?P<end>^[ \t]*(?P=tag)[ \t]*$|\Z)",
    re.DOTALL | re.MULTILINE,
)
# A shell word (quoted runs, escapes and command substitutions glued into one), a redirect, or an operator that ends a
# statement or starts a pipe. Regex, not shlex: shlex reads every character in Python.
_TOKEN = re.compile(
    r"""(?P<redirect>\d*(?:[<>]+|&>)&?-?\d*)"""
    r"""|(?P<op>&&|\|\||[;&|()\n])"""
    r"""|(?P<word>(?:[^\s'"`\\;&|()<>$]+|'[^']*'|"(?:[^"\\]|\\.)*"|`[^`]*`|\\.|\$\((?:[^()]|\([^()]*\))*\)|\$)+)""",
    re.DOTALL,
)
_UNQUOTE = re.compile(r"""'([^']*)'|"((?:[^"\\]|\\.)*)"|\\(.)""", re.DOTALL)
_BIN_SCRIPT = re.compile(r"(?:^|/)(bin/(?:[\w-]+/)?[\w-]+(?:\.py|\.sh)?)$")
_SUBCOMMAND = re.compile(r"^[a-z][\w-]*$")
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
_PYTHON = re.compile(r"^python[\d.]*$")
_NAME = re.compile(r"^[A-Za-z_][\w.:-]*$")
_COMMAND = re.compile(r"^[A-Za-z][\w.+-]*$")
_WRAPPERS = frozenset(
    {"sudo", "doas", "command", "env", "time", "nice", "nohup", "exec", "bash", "sh"}
    | {"do", "then", "else", "elif", "if", "while", "until", "!", "{"}
)
_NOT_WORK = frozenset(
    {"cd", "for", "case", "select", "done", "fi", "esac", "}"}
    | {"echo", "printf", "sleep", "true", "false", ":", "export", "set", "unset"}
)
_PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: ([^\n\\\"'`]+)")
_READ_TOOLS = {"Read": "file_path", "Grep": "path", "Glob": "path"}
_WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
_READS = frozenset({"cat", "head", "tail", "nl", "bat", "less", "more", "wc", "sed"})
_SEARCHES = frozenset({"grep", "egrep", "rg", "find", "fd", "ls", "tree"})
# gh commands that take an argument rather than a verb.
_GH_LEAVES = frozenset({"api", "browse", "status"})
# Flags that take the next word as their value, so it is not an operand.
_VALUE_FLAGS = {
    "git": frozenset({"-C", "-c"}),
    "gh": frozenset({"-R", "--repo"}),
    "make": frozenset({"-C", "-f"}),
    "ssh": frozenset(set("-p -i -l -o -F -J -L -R -D -b -c -E -e -I -m -O -S -W -w -B -Q".split())),
}


def activities(tool: str, tool_input: Mapping[str, Any]) -> list[str]:
    """The activities one tool call performs, in order."""
    if tool not in SHELLS:
        return [tool.rpartition("__")[2] if _NAME.match(tool) else TOOL_OTHER]
    # An export that does not log tool details carries no command; the call is then only the tool's name.
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    return list(_shell(command)) if command else [tool]


def elide_heredocs(command: str) -> str:
    """`command` with each heredoc body replaced by its length in bytes and its SHA-256, so the body is never kept."""

    def mark(found: re.Match[str]) -> str:
        body = found["body"].encode()
        return f"{found['head']}[heredoc length={len(body)} sha256={hashlib.sha256(body).hexdigest()}]\n{found['end']}"

    return _HEREDOC.sub(mark, command)


def _shell(command: str) -> Iterator[str]:
    run = _HEREDOC.sub("", command).replace("\\\n", " ")
    for statement in _statements(run):
        if (activity := _statement(statement)) is not None:
            yield activity


def _statements(command: str) -> Iterator[list[str]]:
    """Each statement's leading pipeline command, as unquoted words."""
    current: list[str] = []
    piped = False
    for token in _TOKEN.finditer(command):
        if token["op"] == "|":
            piped = True
        elif token["op"]:
            yield current
            current, piped = [], False
        elif token["word"] and not piped:
            current.append(_UNQUOTE.sub(lambda m: m[1] or m[2] or m[3] or "", token["word"]))
    yield current


def _unwrap(argv: list[str]) -> list[str]:
    while argv:
        head = argv[0].rpartition("/")[2]
        if _ASSIGNMENT.match(argv[0]) or head in _WRAPPERS or _PYTHON.match(head):
            argv = argv[1:]
        elif head == "timeout":
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv = argv[1:]
            argv = argv[1:]
        elif head == "uv" and argv[1:2] == ["run"]:
            argv = argv[2:]
            while argv and argv[0].startswith("-"):
                argv = argv[1:]
        else:
            return argv
    return argv


def _operands(binary: str, args: list[str]) -> list[str]:
    """`args` without flags, or the value a flag of `binary` takes."""
    operands, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg in _VALUE_FLAGS[binary]:
            skip = True
        elif not arg.startswith("-") and not _ASSIGNMENT.match(arg):
            operands.append(arg)
    return operands


def _statement(argv: list[str]) -> str | None:
    argv = _unwrap(argv)
    if not argv:
        return None
    first = argv[0]
    if script := _BIN_SCRIPT.search(first):
        return script[1]
    binary = first.rpartition("/")[2]
    if binary in _NOT_WORK:
        return None
    if binary in ("make", "git", "gh"):
        words, operands = [], _operands(binary, argv[1:])
        # A worktree verb is kept: `git worktree add` starts a task, `list` only looks.
        for operand in operands[: 2 if binary == "gh" or binary == "git" and operands[:1] == ["worktree"] else 1]:
            if not _SUBCOMMAND.match(operand) or words and words[0] in _GH_LEAVES:
                break
            words.append(operand)
        return " ".join([binary, *words])
    if binary == "ssh":
        host = _operands("ssh", argv[1:])[:1]
        return " ".join(["ssh", *host])
    if binary == "sed" and any(arg.startswith("-i") for arg in argv[1:]):
        return SHELL_OTHER
    if binary in _READS:
        return SHELL_READ
    if binary in _SEARCHES:
        return SHELL_SEARCH
    return binary if _COMMAND.match(binary) else SHELL_OTHER


def paths(tool: str, tool_input: Mapping[str, Any], raw: str) -> tuple[list[str], list[str]]:
    """The paths one tool call reads and writes, as the call named them: a file tool's path argument, or the file
    headers of an `apply_patch` in `raw`, the call's input as the export carries it."""
    if tool == "apply_patch":
        return [], [path.strip() for path in _PATCH_FILE.findall(raw)]
    if (key := _READ_TOOLS.get(tool)) and isinstance(path := tool_input.get(key), str):
        return [path], []
    if (key := _WRITE_TOOLS.get(tool)) and isinstance(path := tool_input.get(key), str):
        return [], [path]
    return [], []
