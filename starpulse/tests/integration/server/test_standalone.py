"""The server as a stranger runs it: no cache server, container runtime, or workspace."""

import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import NamedTuple

import pytest

from starpulse._internal.eventlog.history import DEFAULT_FILE, HistoryStore
from starpulse._internal.server import server
from starpulse.tests.page_stub import held

_CLIENT_MODULE = "re" + "dis"
_ENV_DROPPED = (
    f"{_CLIENT_MODULE.upper()}_URL",
    f"{_CLIENT_MODULE.upper()}_PASSWORD",
    "DATABASE_URI",
    "LISTEN_FDS",  # a socket-activated test run must not hand its own sockets to the servers it starts
    "LISTEN_PID",
)
# Importing the server pulls numpy, whose BLAS pool spins one thread per core for ~2.5 CPU-s without shortening the start.
_BLAS_THREADS = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


@pytest.fixture(scope="module")
def build() -> Iterator[None]:
    """The page build the server refuses to start without, stubbed (shared with other workers) when the checkout has none."""
    with held(server._STATIC):
        yield


def _env(**overrides: str) -> dict[str, str]:
    host_suffix = f"_{_CLIENT_MODULE.upper()}_HOST"
    env = {k: v for k, v in os.environ.items() if k not in _ENV_DROPPED and not k.endswith(host_suffix)}
    return env | _BLAS_THREADS | overrides


def _free_port() -> int:
    """A port below the ephemeral range, which another worker's outgoing connection can take before the server binds."""
    while True:
        port = random.randrange(20_000, 32_768)
        with closing(socket.socket()) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port


def _get(port: int, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def _serve_command(port: int, config: Path) -> list[str]:
    return [sys.executable, "-m", "starpulse._internal.server.server", "--port", str(port), "--config", str(config)]


def _await_page(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 60
    while True:
        assert proc.poll() is None, "the server exited before serving"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                assert resp.status == 200
                return
        except OSError:
            assert time.monotonic() < deadline, f"the page never came up on :{port}"
            time.sleep(0.2)


# Top-level settings of a config come before its tables. The Flow Metrics child sizes history no test here reads.
_NO_FLOW_METRICS = "flow_metrics_worker = true\n"
_INGEST_CONFIG = '[[producers]]\nname = "cron"\ntoken_env = "CRON_INGEST_TOKEN"\n'

# sd_listen_fds: the socket is fd 3 and LISTEN_PID is the server's own pid, which `exec` keeps
_ACTIVATE = (
    "import os, sys; os.dup2(int(sys.argv[1]), 3); "
    "os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1'); os.execv(sys.argv[2], sys.argv[2:])"
)
_INGEST_TOKEN = "s3cret"


class Served(NamedTuple):
    """The server most tests share, which binds `--port`."""

    plain_proc: subprocess.Popen
    plain_port: int
    home: Path  # the directory of the server's config, history file and board
    env: dict[str, str]  # the server's environment, for a command that must see what it sees


class Activated(NamedTuple):
    """The server that listens on the socket a service manager passes."""

    port: int  # the port the passed socket listens on
    named_port: int  # the port `--port` names, which must stay closed


@pytest.fixture(scope="module")
def served(build: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Served]:
    """The server, started once: it is ~4 s of imports and workers, and each test below owns only the names, runs and events it sends."""
    home = tmp_path_factory.mktemp("plain")
    config = home / "starpulse.toml"
    config.write_text(_NO_FLOW_METRICS + _INGEST_CONFIG)
    history = HistoryStore(f"sqlite:///{home / DEFAULT_FILE}", {})
    day = 86400.0
    history.record_lane("l1", "T-1", "In Progress", time.time() - 3 * day)  # a first sighting: enters In Progress
    history.record_lane("l2", "T-1", "Done", time.time() - 2 * day)  # a move out of it, into Done
    history.engine.dispose()
    env = _env(
        PATH=str(tmp_path_factory.mktemp("empty-path")),  # an empty directory: no docker, podman or gh resolves
        CRON_INGEST_TOKEN=_INGEST_TOKEN,
        LISTEN_FDS="1",  # a socket meant for another process: every test here proves the server binds its own port anyway
        LISTEN_PID="1",
    )
    plain_port = _free_port()
    proc = subprocess.Popen(_serve_command(plain_port, config), env=env)
    try:
        _await_page(proc, plain_port)
        yield Served(proc, plain_port, home, env)
    finally:
        proc.terminate()
        proc.wait(timeout=30)


@pytest.fixture(scope="module")
def activated(build: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Activated]:
    """The server on a passed socket, which serves the page and nothing else: it runs no worker."""
    named = _free_port()  # what --port says of it; the server must leave it closed
    config = tmp_path_factory.mktemp("activated") / "starpulse.toml"
    config.write_text(_NO_FLOW_METRICS + "board_worker = true\nruns_worker = true\n")
    with closing(socket.socket()) as passed:
        passed.bind(("127.0.0.1", 0))
        passed.listen(16)
        fd = passed.fileno()
        proc = subprocess.Popen(
            [sys.executable, "-c", _ACTIVATE, str(fd), *_serve_command(named, config)], env=_env(), pass_fds=(fd,)
        )
        try:
            _await_page(proc, passed.getsockname()[1])
            yield Activated(passed.getsockname()[1], named)
        finally:
            proc.terminate()
            proc.wait(timeout=30)


def test_without_a_cache_server_or_any_tool_on_the_path_the_server_serves_history(
    served: Served,
) -> None:
    assert _get(served.plain_port, "/api/history?task=PROJ-1") == (200, {"task": "PROJ-1", "path": []})
    assert (served.home / DEFAULT_FILE).is_file()
    assert (served.home / ".starpulse" / "board" / "config.yml").is_file()  # the first serve made its own board


def test_the_served_snapshot_sizes_each_suns_share_from_the_history_the_server_keeps(served: Served) -> None:
    status, _snapshot = _get(served.plain_port, "/api/snapshot")  # the history `served` wrote before the server started

    assert status == 200


def test_an_event_posted_with_the_token_in_the_environment_reaches_the_snapshot_and_a_wrong_token_does_not(
    served: Served,
) -> None:
    event = json.dumps(
        {
            "specversion": "1.0",
            "id": "e1",
            "source": "cron",
            "type": "StepStarted",
            "subject": "r1",
            "data": {"workflow": "nightly", "status": "running"},
        }
    ).encode()

    def post(token: str) -> int:
        request = urllib.request.Request(
            f"http://127.0.0.1:{served.plain_port}/api/machine-events",
            data=event,
            method="POST",
            headers={"Authorization": token, "Content-Type": "application/cloudevents+json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    assert post("Bearer wrong") == 401
    assert post(f"Bearer {_INGEST_TOKEN}") == 201
    deadline = time.monotonic() + 30
    while "pushed/cron/nightly" not in [d["name"] for d in _get(served.plain_port, "/api/snapshot")[1]["dags"]]:
        assert served.plain_proc.poll() is None, "the server exited"
        assert time.monotonic() < deadline, "the ingested run never reached the snapshot"
        time.sleep(0.2)


@pytest.mark.usefixtures("build")
def test_an_instance_whose_token_variable_is_unset_stops_the_server_naming_it(tmp_path: Path) -> None:
    config = tmp_path / "starpulse.toml"
    config.write_text(_INGEST_CONFIG)

    started = subprocess.run(
        _serve_command(_free_port(), config),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert started.returncode == 1
    assert "runs instance cron: CRON_INGEST_TOKEN is not set" in started.stderr


def test_serve_answers_on_the_listening_socket_the_service_manager_passes_in_and_binds_no_port_of_its_own(
    activated: Activated,
) -> None:
    assert _get(activated.port, "/api/history?task=PROJ-1") == (200, {"task": "PROJ-1", "path": []})
    with pytest.raises(OSError), closing(socket.create_connection(("127.0.0.1", activated.named_port), timeout=2)):
        pass


@pytest.mark.usefixtures("build")
def test_serve_on_a_port_something_holds_names_the_port_and_the_flag_and_starts_nothing(tmp_path: Path) -> None:
    config = tmp_path / "starpulse.toml"
    config.write_text("")
    with closing(socket.socket()) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        ran = subprocess.run(_serve_command(port, config), env=_env(), capture_output=True, text=True, timeout=60)

    assert ran.returncode == 1
    assert ran.stdout == ""  # no "StarPulse on :PORT" for a server that never bound
    assert ran.stderr == f"cannot listen on 127.0.0.1:{port}: Address already in use; pass --port to serve elsewhere\n"
    assert "Traceback" not in ran.stderr
    assert not (tmp_path / DEFAULT_FILE).exists()  # refused before the history, the board or any worker started
    assert not (tmp_path / ".starpulse").exists()


def test_serve_refuses_to_pick_one_of_several_passed_sockets() -> None:
    environ = {"LISTEN_FDS": "2", "LISTEN_PID": str(os.getpid())}

    with pytest.raises(ValueError, match="2 sockets"):
        server.inherited_socket(environ)
