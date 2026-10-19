"""The ingest on a machine with no Redis: declare a machine, post its events over HTTP, read them back.

Usage: python3 -I ci/clean_machine.py PYTHON   (PYTHON is the interpreter of a venv holding the installed wheel)

Fails unless every step holds, in order:

1. no Redis port answers on 127.0.0.1 (6379 and the TLS port 6380), so what follows cannot lean on one;
2. `starpulse serve` starts in an empty directory holding one `.starpulse/machines/` file and one `[[producers]]` entry;
3. the declared events, POSTed to `/api/machine-events` with the producer's token, answer 201;
4. they come back from the event log (the sqlite history file beside the config) and from the SSE stream `/api/events`;
5. an event the machine does not declare is refused 4xx and never reaches the log.

Stdlib only, run as `python3 -I` so nothing beside the script is importable; it works the same on Linux and macOS.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEADLINE = 60.0
REDIS_PORTS = (6379, 6380)
TOKEN = "clean-machine-token"
PRODUCER = "builder"
CLOUDEVENTS = "application/cloudevents+json"
MACHINE = """\
name: delivery
states:
  start: {initial: true}
  built: {}
  shipped: {final: true}
events:
  BUILT:
    - {from: start, to: built}
  SHIPPED:
    - {from: built, to: shipped}
writers:
  BUILT: [{actor: ci, trigger: "the build job"}]
  SHIPPED: [{actor: ci, trigger: "the deploy job"}]
"""
CONFIG = f"""\
[[producers]]
name = "{PRODUCER}"
token_env = "CLEAN_MACHINE_TOKEN"
machines = ["delivery"]
actors = ["ci"]
"""


def redis_answering(ports: tuple[int, ...], host: str = "127.0.0.1") -> list[int]:
    """The ports among `ports` that accept a connection on `host`."""
    answering = []
    for port in ports:
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                answering.append(port)
    return answering


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cloudevent(event_id: str, kind: str, run: str) -> dict:
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": PRODUCER,
        "type": kind,
        "run": run,
        "machine": "delivery",
        "actor": "ci",
    }


def post(port: int, event: dict, token: str = TOKEN) -> int:
    """The HTTP status of posting `event` to the ingest."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/machine-events",
        data=json.dumps(event).encode(),
        method="POST",
        headers={"Content-Type": CLOUDEVENTS, "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status
    except urllib.error.HTTPError as error:
        return error.code


def logged(directory: Path) -> list[tuple[str, str]]:
    """The `(event, run)` of every machine event in the sqlite event log beside the config, in order."""
    found = []
    for database in directory.glob("*.sqlite"):
        with sqlite3.connect(database) as connection:
            try:
                rows = connection.execute(
                    "select fields from starpulse_events where stream = ? order by id", ("machine:events",)
                ).fetchall()
            except sqlite3.OperationalError:  # serve has not created the table yet
                continue
        found += [(json.loads(fields)["event"], json.loads(fields)["run"]) for (fields,) in rows]
    return found


class Placed:
    """The `(flow, id)` of every task `/api/events` places once opened; `opened` is set at its first event.

    A `move` event places one task. A machine that is still replaying its history when an event lands sends the
    placement in the snapshot that ends the replay instead, so a snapshot's flows count as well.
    """

    def __init__(self, port: int) -> None:
        self.tasks: set[tuple[str, str]] = set()
        self.opened = threading.Event()
        self._port = port
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        name, first = "", True
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/api/events", timeout=DEADLINE) as stream:
                for raw in stream:
                    line = raw.decode().rstrip("\n")
                    if line.startswith("event:"):
                        name = line.removeprefix("event:").strip()
                        first = not self.opened.is_set()
                        self.opened.set()
                    elif line.startswith("data:") and name == "move":
                        data = json.loads(line.removeprefix("data:").strip())
                        self.tasks.add((data["flow"], data["id"]))
                    elif line.startswith("data:") and name == "snapshot" and not first:
                        for flow in json.loads(line.removeprefix("data:").strip()).get("flows", []):
                            self.tasks |= {(flow["name"], agent["id"]) for agent in flow["agents"]}
        except OSError:
            pass  # the server went down at the end of the run


def wait_for_page(port: int, serve: subprocess.Popen, deadline: float) -> str | None:
    end = time.monotonic() + deadline
    while time.monotonic() < end and serve.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return None
        except urllib.error.HTTPError:
            return None
        except OSError:
            time.sleep(0.5)
    return f"serve exited {serve.returncode}" if serve.poll() is not None else "serve never answered"


def smoke(python: str, deadline: float) -> str | None:
    """Run the whole proof and return the first thing that failed, or None."""
    if answering := redis_answering(REDIS_PORTS):
        return f"a Redis port answers on {answering}: the proof needs a machine without one"
    with tempfile.TemporaryDirectory() as empty:
        base = Path(empty)
        (base / ".starpulse" / "machines").mkdir(parents=True)
        (base / ".starpulse" / "machines" / "delivery.yaml").write_text(MACHINE)
        (base / "starpulse.toml").write_text(CONFIG)
        port = free_port()
        env = {"PATH": os.environ["PATH"], "HOME": empty, "CLEAN_MACHINE_TOKEN": TOKEN}
        with (base / "serve.log").open("w") as sink:
            serve = subprocess.Popen(
                [python, "-m", "starpulse", "serve", "--port", str(port)], cwd=empty, env=env, stderr=sink
            )
        try:
            if problem := wait_for_page(port, serve, deadline):
                return problem
            stream = Placed(port)
            if not stream.opened.wait(deadline):
                return "SSE /api/events sent nothing"
            events = [cloudevent("e1", "BUILT", "r1"), cloudevent("e2", "SHIPPED", "r1")]
            sent = []
            for event in events:
                if (status := post(port, event)) != 201:
                    return f"{event['type']} answered HTTP {status}, not 201"
                sent.append((event["type"], event["run"]))
            end = time.monotonic() + deadline
            while time.monotonic() < end and (logged(base) != sent or ("delivery", "r1") not in stream.tasks):
                time.sleep(0.5)
            if (found := logged(base)) != sent:
                return f"the event log holds {found}, not {sent}"
            if ("delivery", "r1") not in stream.tasks:
                return f"SSE /api/events placed {sorted(stream.tasks)}, not delivery/r1"
            if (status := post(port, cloudevent("e3", "UNDECLARED", "r2"))) // 100 != 4:
                return f"an undeclared event answered HTTP {status}, not 4xx"
            if (status := post(port, cloudevent("e4", "BUILT", "r3"), token="wrong")) // 100 != 4:
                return f"a wrong token answered HTTP {status}, not 4xx"
            if (found := logged(base)) != sent:
                return f"a refused event reached the log: {found}"
            return None
        finally:
            serve.terminate()
            try:
                serve.wait(10)
            except subprocess.TimeoutExpired:
                serve.kill()


def main(argv: list[str]) -> int:
    problem = smoke(argv[0], float(argv[1]) if len(argv) > 1 else DEADLINE)
    print(problem or "ok: no Redis answered; two events posted, read from the event log and SSE; an undeclared one refused 4xx")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
