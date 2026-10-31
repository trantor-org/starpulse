"""The ingest on a machine with no Redis: declare a machine, post its events over HTTP and gRPC, read them back.

Usage: python3 -I ci/clean_machine.py PYTHON   (PYTHON is the interpreter of a venv holding the installed wheel)

Fails unless every step holds, in order:

1. no Redis port answers on 127.0.0.1 (6379 and the TLS port 6380), so what follows cannot lean on one;
2. `starpulse migrate`, then `starpulse serve`, start in an empty directory holding one `.starpulse/machines/` file and
   one `[[producers]]` entry (serve refuses a store migrate has not brought to its schema);
3. the declared events, POSTed to `/api/machine-events` with the producer's token, answer 201;
4. they come back from the event log (the sqlite history file beside the config) and from the SSE stream `/api/events`;
5. an event the machine does not declare is refused 4xx and never reaches the log;
6. the same server takes a CloudEvent over gRPC on the same port (`starpulse.v1.CloudEventsIngest/Publish`, sent by
   the wheel venv's own connect-python client): a declared event is accepted and read back from the log, an
   undeclared one and a wrong token are refused with a non-OK gRPC status and never reach the log.

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
STDERR_TAIL = 2000
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


GRPC_CLIENT = """\
import sys

from connectrpc.client import ConnectClientSync
from connectrpc.errors import ConnectError
from connectrpc.method import IdempotencyLevel, MethodInfo
from connectrpc.protocol import ProtocolType
from google.protobuf.empty_pb2 import Empty
from pyqwest import HTTPVersion, SyncClient, SyncHTTPTransport

from starpulse.runs.adapters.inbound.wire.cloudevents_pb2 import CloudEvent

port, token, kind, run = sys.argv[1:]
client = ConnectClientSync(
    f"http://127.0.0.1:{port}",
    protocol=ProtocolType.GRPC,
    http_client=SyncClient(SyncHTTPTransport(http_version=HTTPVersion.HTTP2)),
)
method = MethodInfo(
    name="Publish",
    service_name="starpulse.v1.CloudEventsIngest",
    input=CloudEvent,
    output=Empty,
    idempotency_level=IdempotencyLevel.UNKNOWN,
)
event = CloudEvent(id=run, source="builder", spec_version="1.0", type=kind)
for name, value in {"run": run, "machine": "delivery", "actor": "ci"}.items():
    event.attributes[name].ce_string = value
try:
    client.execute_unary(request=event, method=method, headers={"authorization": f"Bearer {token}"}, timeout_ms=5000)
    print("OK")
except ConnectError as error:
    print(error.code.name)
"""


def publish_grpc(python: str, port: int, kind: str, run: str, token: str = TOKEN) -> str:
    """The gRPC status name of publishing one `kind` event of `run`, sent by `python`'s own connect-python client."""
    done = subprocess.run(
        [python, "-I", "-c", GRPC_CLIENT, str(port), token, kind, run],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return done.stdout.strip() or f"client exited {done.returncode}: {done.stderr.strip()[-200:]}"


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
                        self.tasks.add((data["machine"], data["id"]))
                    elif line.startswith("data:") and name == "snapshot" and not first:
                        for flow in json.loads(line.removeprefix("data:").strip()).get("flows", []):
                            self.tasks |= {(flow["name"], agent["id"]) for agent in flow["agents"]}
        except OSError:
            pass  # the server went down at the end of the run


def migrate(python: str, base: Path, env: dict[str, str]) -> str | None:
    """Bring the store in `base` to its schema, as a clean install does before `serve`; the problem, or None."""
    done = subprocess.run(
        [python, "-m", "starpulse", "migrate"],
        cwd=base,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return (
        f"starpulse migrate exited {done.returncode}: {done.stderr.strip()[-STDERR_TAIL:]}" if done.returncode else None
    )


def wait_for_page(port: int, serve: subprocess.Popen, deadline: float, log: Path) -> str | None:
    """None once the page answers; else why not, with the tail of `log`, where `serve` wrote its stderr."""
    end = time.monotonic() + deadline
    while time.monotonic() < end and serve.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return None
        except urllib.error.HTTPError:
            return None
        except OSError:
            time.sleep(0.5)
    if serve.poll() is None:
        return "serve never answered"
    return f"serve exited {serve.returncode}: {log.read_text().strip()[-STDERR_TAIL:]}"


def grpc_problem(python: str, port: int, base: Path, sent: list[tuple[str, str]]) -> str | None:
    """The first thing that fails when the server takes `sent`'s events over gRPC too, or None; appends the one it takes."""
    if (status := publish_grpc(python, port, "BUILT", "r4")) != "OK":
        return f"gRPC Publish of a declared event answered {status}, not OK"
    sent.append(("BUILT", "r4"))
    if (status := publish_grpc(python, port, "UNDECLARED", "r5")) in {
        "OK",
        "UNIMPLEMENTED",
    } or status.startswith("client"):
        return f"gRPC Publish of an undeclared event answered {status}, not a refusal"
    if (status := publish_grpc(python, port, "BUILT", "r6", token="wrong")) != "UNAUTHENTICATED":
        return f"gRPC Publish under a wrong token answered {status}, not UNAUTHENTICATED"
    if (found := logged(base)) != sent:
        return f"the gRPC events in the log are {found}, not {sent}"
    return None


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
        if problem := migrate(python, base, env):
            return problem
        log = base / "serve.log"
        with log.open("w") as sink:
            serve = subprocess.Popen(
                [python, "-m", "starpulse", "serve", "--port", str(port)], cwd=empty, env=env, stderr=sink
            )
        try:
            if problem := wait_for_page(port, serve, deadline, log):
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
            return grpc_problem(python, port, base, sent)
        finally:
            serve.terminate()
            try:
                serve.wait(10)
            except subprocess.TimeoutExpired:
                serve.kill()


def main(argv: list[str]) -> int:
    problem = smoke(argv[0], float(argv[1]) if len(argv) > 1 else DEADLINE)
    print(
        problem
        or "ok: no Redis answered; two events posted, read from the event log and SSE; an undeclared one refused 4xx; one more published and two refused over gRPC"
    )
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
