"""The interpreter `serve` starts its processes on, and the directory a re-executed `serve` runs from.

`serve` is started through a path that names a release by a symlink (`current/.venv/bin/starpulse`). The interpreter
beside that script is reached through the same symlink, so it is the release the link names *now*: a process started
on it, and a `serve` that re-executes on it, run the release a deploy moved the link to, where `sys.executable` is
fixed to the release `serve` itself started in.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def interpreter(argv0: str | None = None, executable: str | None = None) -> str:
    """The `python` beside the script `serve` was started by, else the interpreter running now.

    The path is made absolute but never resolved, so a symlink in it is followed again each time it is used."""
    beside = Path(os.path.abspath(argv0 or sys.argv[0])).parent / "python"
    return str(beside) if beside.is_file() else executable or sys.executable


def workdir(python: str) -> Path | None:
    """The directory holding the virtual environment `python` lives in, or None outside one."""
    path = Path(python)
    return path.parents[1].parent if path.parent.name == "bin" and (path.parents[1] / "pyvenv.cfg").is_file() else None


def exec_self() -> None:  # pragma: no mutate block — process boundary
    """Replace this process with `serve` on the interpreter now behind the launcher, in that release's directory.

    The release then current is the directory the relative config path and the control file resolve against."""
    python = interpreter()
    directory = workdir(python)
    if directory is not None:
        os.chdir(directory)
    os.execv(python, [python, *sys.orig_argv[1:]])
