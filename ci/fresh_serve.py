"""Smoke the out-of-the-box install: `starpulse serve` from an empty virtualenv, directory and config.

Usage: fresh_serve.py VENV_PYTHON [DEADLINE_SECONDS]

The interpreter is the one of a virtualenv that holds only the installed wheel. `serve` starts in an empty directory with
no `starpulse.toml` and a bare environment, so nothing of the checkout is on its path. It must answer HTTP 200 on `/`
and hold one live worker below it for every context `worker_commands` starts for the default config, on two checks a
moment apart with the same processes, so a child that restarts in a loop fails. A worker's context is the one `serve`
logged for its pid (a zygote-forked child shows the zygote's argv in `ps`); its liveness and ancestry are read from `ps`,
so it runs on Linux and macOS.
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEADLINE = 60.0
SETTLE = 5.0
LOG_TAIL = 20000
STARTED = re.compile(r"worker ([\w-]+) started as pid (\d+)")


def process_table() -> dict[int, tuple[int, str]]:
    """Every process's parent pid and state, by pid."""
    table = subprocess.run(["ps", "-axo", "pid=,ppid=,stat="], capture_output=True, text=True, check=True)
    return {int(pid): (int(ppid), state) for pid, ppid, state in map(str.split, table.stdout.splitlines())}


def descends_from(pid: int, ancestor: int, table: dict[int, tuple[int, str]]) -> bool:
    while pid in table and pid != ancestor:
        pid = table[pid][0]
    return pid == ancestor


def live_children(parent: int, log: Path) -> dict[str, int]:
    """The pid of each context's live worker below `parent`, from the pid the supervisor last logged for it.

    A worker forked from the zygote has the zygote's argv and a ppid of the zygote, so `ps` cannot name its context.
    """
    started = {name: int(pid) for name, pid in STARTED.findall(log.read_text())}
    table = process_table()
    return {
        name: pid
        for name, pid in started.items()
        if pid in table and not table[pid][1].startswith("Z") and descends_from(pid, parent, table)
    }


def check(port: int, parent: int, expected: set[str], log: Path, scheme: str = "http") -> str | None:
    """None when the page answers 200 and every expected context has a live child, else what is missing.

    Over `https` the probe asks about liveness, not trust: it takes any certificate.
    """
    tls = ssl._create_unverified_context() if scheme == "https" else None  # noqa: S323 - a liveness probe, not trust
    try:
        with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/", timeout=5, context=tls) as page:
            status = page.status
    except urllib.error.HTTPError as error:
        status = error.code
    except OSError as error:
        return f"page unreachable: {error}"
    if status != 200:
        return f"page answered HTTP {status}"
    if missing := sorted(expected - live_children(parent, log).keys()):
        return f"{', '.join(missing)} down: no live child"
    return None


def worker_contexts(python: str, cwd: str) -> set[str]:
    """The contexts `serve` supervises under the default config, which has no embeddings URL."""
    code = (
        "import json; from starpulse.runtime.config import discover, load;"
        " from starpulse.runtime.supervisor import worker_commands;"
        " print(json.dumps(sorted(worker_commands(load(discover(None)), None))))"
    )
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
        log = Path(empty, "serve.log")
        subprocess.run([python, "-m", "starpulse", "migrate"], cwd=empty, env=env, check=True)
        with log.open("w") as sink:
            serve = subprocess.Popen(
                [python, "-m", "starpulse", "serve", "--port", str(port)], cwd=empty, env=env, stderr=sink
            )
        try:
            problem = "serve did not start"
            end = time.monotonic() + deadline
            while time.monotonic() < end and serve.poll() is None:
                if (problem := check(port, serve.pid, expected, log)) is None:
                    before = live_children(serve.pid, log)
                    time.sleep(SETTLE)
                    problem = check(port, serve.pid, expected, log)
                    if problem is None and live_children(serve.pid, log) == before:
                        return None
                    problem = problem or "a child restarted"
                time.sleep(0.5)
            problem = problem if serve.poll() is None else f"serve exited {serve.returncode}"
        finally:
            serve.terminate()
            try:
                serve.wait(10)
            except subprocess.TimeoutExpired:
                serve.kill()
        return f"{problem}\n--- serve stderr ---\n{log.read_text()[-LOG_TAIL:]}"


def main(argv: list[str]) -> int:
    problem = smoke(argv[0], float(argv[1]) if len(argv) > 1 else DEADLINE)
    print(problem or "ok: page 200 and every worker child alive")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
