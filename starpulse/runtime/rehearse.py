"""`starpulse rehearse --config FILE --database-url URL`: start the real `serve` on a copy of a store and report whether it got ready.

It migrates the store `--database-url` names through the config (`starpulse migrate`), starts `serve` from the same
config on a loopback port the kernel picks, with TLS, telemetry, adapters, producers and every outbound call off and
pruned rows archived in a scratch directory (`config.rehearsal`), polls `GET /api/ready` until it answers 200 or
`--budget` seconds pass, and stops the server. It exits 0 only when the server got ready, and otherwise 1 naming
what did not. The store must be a copy: the rehearsal migrates it and `serve` writes to it.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from starpulse.runtime.config import REHEARSE_ENV

#: Seconds the whole rehearsal may take unless `--budget` says otherwise.
BUDGET_S = 120.0

#: Seconds between two reads of `/api/ready`, and how long a read may take.
POLL_S = 0.5
READ_S = 2.0

#: Seconds `serve` is given to end after `SIGTERM` before it is killed.
STOP_S = 20.0

Command = Callable[[Path, int], list[str]]


def serve_command(config: Path, port: int) -> list[str]:
    """The `serve` a rehearsal starts: loopback only, on `port`."""
    return [sys.executable, "-m", "starpulse", "serve", "--config", str(config), "--host", "127.0.0.1", "--port", str(port)]


def migrate_command(config: Path) -> list[str]:
    return [sys.executable, "-m", "starpulse", "migrate", "--config", str(config)]


def store_url(database_url: str) -> str:
    """`database_url` as a SQLAlchemy URL: a plain path names a SQLite file."""
    return database_url if "://" in database_url else f"sqlite:///{Path(database_url).resolve()}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read_ready(port: int) -> tuple[int | None, dict | None]:
    """The status and JSON body `/api/ready` answers on `port`; `None` status while nothing answers."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ready", timeout=READ_S) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, None
    except (OSError, ValueError):
        return None, None


def unready(body: dict | None) -> str:
    """The components `/api/ready` named as not ready, each with its detail."""
    components = (body or {}).get("components", {})
    return "; ".join(f"{name}: {part['detail']}" for name, part in components.items() if not part["ready"])


def stop(server: subprocess.Popen) -> None:
    """End `server` with `SIGTERM`, which makes it stop its workers, and kill it if it stays."""
    if server.poll() is not None:
        return
    os.killpg(server.pid, signal.SIGTERM)
    try:
        server.wait(STOP_S)
    except subprocess.TimeoutExpired:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait()


def tail(log: Path, lines: int = 15) -> str:
    return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])


def rehearse(
    config: Path,
    database_url: str,
    budget: float = BUDGET_S,
    *,
    serve: Command = serve_command,
    migrate: Callable[[Path], list[str]] = migrate_command,
    poll_s: float = POLL_S,
) -> str | None:
    """`None` when the server got ready within `budget`, else the reason it did not."""
    deadline = time.monotonic() + budget
    with tempfile.TemporaryDirectory(prefix="starpulse-rehearse-") as scratch:
        spec = {"database_url": store_url(database_url), "archive_dir": str(Path(scratch) / "archive")}
        env = {**os.environ, REHEARSE_ENV: json.dumps(spec)}
        log = Path(scratch) / "rehearse.log"
        with log.open("w") as out:
            try:
                migrated = subprocess.run(
                    migrate(config), env=env, stdout=out, stderr=subprocess.STDOUT, timeout=budget, check=False
                )
            except subprocess.TimeoutExpired:
                return f"migrate did not finish within {budget:.0f}s\n{tail(log)}"
            if migrated.returncode:
                return f"migrate exited {migrated.returncode}\n{tail(log)}"
            port = free_port()
            server = subprocess.Popen(
                serve(config, port), env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
            )
        try:
            last: tuple[int | None, dict | None] = (None, None)
            while time.monotonic() < deadline:
                if (code := server.poll()) is not None:
                    return f"serve exited {code} before it was ready\n{tail(log)}"
                last = read_ready(port)
                if last[0] == 200:
                    return None
                time.sleep(poll_s)
            status, body = last
            why = unready(body) or ("nothing answered" if status is None else f"/api/ready answered {status}")
            return f"not ready within {budget:.0f}s: {why}\n{tail(log)}"
        finally:
            stop(server)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse rehearse", description="start serve on a copy of a store and wait for ready")
    parser.add_argument("--config", type=Path, required=True, help="the TOML config the server runs with")
    parser.add_argument("--database-url", required=True, help="the COPY of the store to migrate and serve: a URL or a SQLite file")
    parser.add_argument("--budget", type=float, default=BUDGET_S, help="seconds the whole rehearsal may take; default %(default)s")
    args = parser.parse_args(argv)
    failed = rehearse(
        args.config, args.database_url, args.budget, serve=serve_command, migrate=migrate_command, poll_s=POLL_S
    )
    if failed:
        print(f"rehearse failed: {failed}", file=sys.stderr)
        return 1
    print("rehearse: ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
