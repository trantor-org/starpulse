"""Smoke the out-of-the-box install: `starpulse serve` from an empty virtualenv, directory and config.

Usage: fresh_serve.py VENV_PYTHON [DEADLINE_SECONDS]

The interpreter is the one of a virtualenv that holds only the installed wheel. `serve` starts in an empty directory with
no `starpulse.toml` and a bare environment, so nothing of the checkout is on its path. It must answer HTTP 200 on `/`
and hold one live `starpulse worker <context>` child for every context `WORKER_FLAGS` names, on two checks a moment
apart with the same processes, so a child that restarts in a loop fails. Linux only: the children are read from /proc.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEADLINE = 60.0
SETTLE = 5.0


def live_children(parent: int) -> dict[str, int]:
    """The pid of each live `starpulse worker <context>` child of `parent`, by context."""
    found = {}
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            status = dict(line.split(":\t", 1) for line in (entry / "status").read_text().splitlines() if ":\t" in line)
            argv = (entry / "cmdline").read_bytes().decode().split("\0")
        except OSError, ValueError:
            continue
        if int(status["PPid"]) == parent and not status["State"].startswith("Z") and "worker" in argv[:-1]:
            found[argv[argv.index("worker") + 1]] = int(entry.name)
    return found


def check(port: int, parent: int, expected: set[str]) -> str | None:
    """None when the page answers 200 and every expected context has a live child, else what is missing."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as page:
            status = page.status
    except urllib.error.HTTPError as error:
        status = error.code
    except OSError as error:
        return f"page unreachable: {error}"
    if status != 200:
        return f"page answered HTTP {status}"
    if missing := sorted(expected - live_children(parent).keys()):
        return f"no live child for {', '.join(missing)}"
    return None


def worker_contexts(python: str, cwd: str) -> set[str]:
    code = "import json; from starpulse._internal.server.supervisor import WORKER_FLAGS; print(json.dumps(sorted(WORKER_FLAGS)))"
    return set(
        json.loads(
            subprocess.run([python, "-I", "-c", code], cwd=cwd, capture_output=True, text=True, check=True).stdout
        )
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def smoke(python: str, deadline: float) -> str | None:
    """Run `serve` and return the last problem seen when it never passes within `deadline` seconds, else None."""
    with tempfile.TemporaryDirectory() as empty:
        expected = worker_contexts(python, empty)
        port = free_port()
        env = {"PATH": os.environ["PATH"], "HOME": empty}
        serve = subprocess.Popen([python, "-m", "starpulse", "serve", "--port", str(port)], cwd=empty, env=env)
        try:
            problem = "serve did not start"
            end = time.monotonic() + deadline
            while time.monotonic() < end and serve.poll() is None:
                if (problem := check(port, serve.pid, expected)) is None:
                    before = live_children(serve.pid)
                    time.sleep(SETTLE)
                    if (problem := check(port, serve.pid, expected)) is None and live_children(serve.pid) == before:
                        return None
                    problem = problem or "a child restarted"
                time.sleep(0.5)
            return problem if serve.poll() is None else f"serve exited {serve.returncode}"
        finally:
            serve.terminate()
            try:
                serve.wait(10)
            except subprocess.TimeoutExpired:
                serve.kill()


def main(argv: list[str]) -> int:
    problem = smoke(argv[0], float(argv[1]) if len(argv) > 1 else DEADLINE)
    print(problem or "ok: page 200 and every worker child alive")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
