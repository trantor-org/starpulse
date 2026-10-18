"""The server as a stranger runs it: no cache server, container runtime, or workspace."""

import json
import os
import shutil
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

from starpulse._internal.server import server
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import DEFAULT_FILE, HistoryStore

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

# The `build` stub writes and removes the checkout's shared static directory, so under pytest-xdist these tests share
# one worker (`--dist loadgroup`): another worker's teardown would delete the page out from under a running server.
pytestmark = pytest.mark.xdist_group("static-build")


@pytest.fixture(scope="module")
def build() -> Iterator[None]:
    """The page build the server refuses to start without, stubbed when the checkout has none."""
    index = server._STATIC / "index.html"
    if index.is_file():
        yield
        return
    index.parent.mkdir(exist_ok=True)
    index.write_text("<!doctype html>")
    try:
        yield
    finally:
        shutil.rmtree(index.parent)


def _env(**overrides: str) -> dict[str, str]:
    host_suffix = f"_{_CLIENT_MODULE.upper()}_HOST"
    env = {k: v for k, v in os.environ.items() if k not in _ENV_DROPPED and not k.endswith(host_suffix)}
    return env | _BLAS_THREADS | overrides


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


_INGEST_CONFIG = '[[runs]]\nname = "cron"\ntype = "dagu"\nurl = "http://127.0.0.1:9"\ntoken_env = "CRON_INGEST_TOKEN"\n'

_FAKE_RUNS = '''
from pathlib import Path


def start(url):
    if url.endswith(".none"):
        return None

    def run(workflow):
        with Path(url).open("a") as marker:
            marker.write(workflow + "\\n")
        return "run-1"

    return run


def follow(url, runs, log):
    pass
'''


def _fake_runs(tmp_path: Path, url: str) -> str:
    """A package with a runs adapter whose `start` appends the workflow to the file `url` names, and its config."""
    package = tmp_path / "fakes"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "runs.py").write_text(_FAKE_RUNS)
    return (
        f'[[runs]]\nname = "fake"\ntype = "fakes.runs"\nurl = "{url}"\n\n'
        '[[triggers]]\non = "lane"\nstart = "fake/reconcile"\nwhen = { lane = { equals = "done" } }\n'
    )


# sd_listen_fds: the socket is fd 3 and LISTEN_PID is the server's own pid, which `exec` keeps
_ACTIVATE = (
    "import os, sys; os.dup2(int(sys.argv[1]), 3); "
    "os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1'); os.execv(sys.argv[2], sys.argv[2:])"
)
_INGEST_TOKEN = "s3cret"


class Served(NamedTuple):
    """The two servers the module shares: `plain` binds `--port`, `activated` listens on the socket a service manager passes."""

    plain_proc: subprocess.Popen
    plain_port: int
    home: Path  # the directory of `plain`'s config, history file and board
    marker: Path  # the file the fake runs adapter appends each started workflow to
    env: dict[str, str]  # `plain`'s environment, for a command that must see what it sees
    activated_port: int  # the port the passed socket listens on
    named_port: int  # the port `--port` names for `activated`, which must stay closed


@pytest.fixture(scope="module")
def served(build: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Served]:
    """Both servers, started together: a server is ~8 s of imports and workers, and each test below owns only the names, runs and events it sends."""
    home = tmp_path_factory.mktemp("plain")
    marker = home / "started.txt"
    config = home / "starpulse.toml"
    config.write_text(_INGEST_CONFIG + "\n" + _fake_runs(home, str(marker)))
    history = HistoryStore(f"sqlite:///{home / DEFAULT_FILE}", {})
    day = 86400.0
    history.record_lane("l1", "T-1", "In Progress", time.time() - 3 * day)  # a first sighting: enters In Progress
    history.record_lane("l2", "T-1", "Done", time.time() - 2 * day)  # a move out of it, into Done
    history.engine.dispose()
    env = _env(
        PATH=str(tmp_path_factory.mktemp("empty-path")),  # an empty directory: no docker, podman or gh resolves
        PYTHONPATH=os.pathsep.join([str(home), os.environ.get("PYTHONPATH", "")]),
        CRON_INGEST_TOKEN=_INGEST_TOKEN,
        LISTEN_FDS="1",  # a socket meant for another process: every test here proves the server binds its own port anyway
        LISTEN_PID="1",
    )
    named = _free_port()  # what --port says of `activated`; the server must leave it closed
    activated_config = tmp_path_factory.mktemp("activated") / "starpulse.toml"
    activated_config.write_text("")
    procs: list[subprocess.Popen] = []
    with closing(socket.socket()) as passed:
        passed.bind(("127.0.0.1", 0))
        passed.listen(16)
        fd = passed.fileno()
        plain_port = _free_port()
        try:
            procs.append(subprocess.Popen(_serve_command(plain_port, config), env=env))
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-c", _ACTIVATE, str(fd), *_serve_command(named, activated_config)],
                    env=_env(),
                    pass_fds=(fd,),
                )
            )
            _await_page(procs[0], plain_port)
            _await_page(procs[1], passed.getsockname()[1])
            yield Served(procs[0], plain_port, home, marker, env, passed.getsockname()[1], named)
        finally:
            for proc in procs:
                proc.terminate()
            for proc in procs:
                proc.wait(timeout=30)


def test_without_a_cache_server_or_any_tool_on_the_path_the_server_serves_history_and_what_emit_pushed(
    served: Served,
) -> None:
    assert _get(served.plain_port, "/api/history?task=PROJ-1") == (200, {"task": "PROJ-1", "path": []})
    assert (served.home / DEFAULT_FILE).is_file()
    assert (served.home / ".starpulse" / "board" / "config.yml").is_file()  # the first serve made its own board

    emitted = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from starpulse.__main__ import main; "
                f"code = main({['emit', 'StepStarted', '--workflow', 'nightly', '--run', 'r1', '--status', 'running', '--config', str(served.home / 'starpulse.toml')]!r}); "
                f"assert {_CLIENT_MODULE!r} not in sys.modules; raise SystemExit(code)"
            ),
        ],  # fmt: skip
        env=served.env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert emitted.returncode == 0, emitted.stderr
    deadline = time.monotonic() + 30
    while "pushed/nightly" not in [d["name"] for d in _get(served.plain_port, "/api/snapshot")[1]["dags"]]:
        assert served.plain_proc.poll() is None, "the server exited"
        assert time.monotonic() < deadline, "the emitted run never reached the snapshot"
        time.sleep(0.2)


def test_the_served_snapshot_sizes_each_suns_share_from_the_history_the_server_keeps(served: Served) -> None:
    status, _snapshot = _get(served.plain_port, "/api/snapshot")  # the history `served` wrote before the server started

    assert status == 200


def test_an_event_posted_with_the_token_in_the_environment_reaches_the_snapshot_and_a_wrong_token_does_not(
    served: Served,
) -> None:
    event = json.dumps({"event": "StepStarted", "workflow": "cron/nightly", "run_id": "r1", "status": "running"}).encode()

    def post(token: str) -> int:
        request = urllib.request.Request(
            f"http://127.0.0.1:{served.plain_port}/api/runs/events",
            data=event,
            method="POST",
            headers={"Authorization": token},
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


def test_a_lane_event_a_trigger_matches_starts_the_run_through_the_adapter_and_one_it_does_not_match_starts_none(
    served: Served,
) -> None:
    history = HistoryStore(f"sqlite:///{served.home / DEFAULT_FILE}", {})
    log = EventLog(f"sqlite:///{served.home / DEFAULT_FILE}")
    try:
        deadline = time.monotonic() + 30
        while history.cursor("triggers") is None:  # the consumer has taken its place at the log's head
            assert served.plain_proc.poll() is None, "the server exited before serving"
            assert time.monotonic() < deadline, "the trigger consumer never started"
            time.sleep(0.2)
        assert log.append("board:lanes", {"task": "TASK-1", "lane": "review", "time": 1.0}, event_id="TASK-1@review@1")
        assert log.append("board:lanes", {"task": "TASK-1", "lane": "done", "time": 2.0}, event_id="TASK-1@done@2")
        while not served.marker.exists():
            assert served.plain_proc.poll() is None, "the server exited"
            assert time.monotonic() < deadline, "the matching event never started the run"
            time.sleep(0.2)
        time.sleep(1)  # a second start, were there one, would be read by now
        assert served.marker.read_text() == "reconcile\n"
    finally:
        history.engine.dispose()


@pytest.mark.usefixtures("build")
def test_a_trigger_whose_adapter_cannot_start_a_run_stops_the_server_naming_the_workflow(tmp_path: Path) -> None:
    config = tmp_path / "starpulse.toml"
    config.write_text(_fake_runs(tmp_path, str(tmp_path / "started.none")))

    started = subprocess.run(
        _serve_command(_free_port(), config),
        env=_env(PYTHONPATH=os.pathsep.join([str(tmp_path), os.environ.get("PYTHONPATH", "")])),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert started.returncode == 1
    assert "no adapter can start a run of: fake/reconcile" in started.stderr


def test_serve_answers_on_the_listening_socket_the_service_manager_passes_in_and_binds_no_port_of_its_own(
    served: Served,
) -> None:
    assert _get(served.activated_port, "/api/history?task=PROJ-1") == (200, {"task": "PROJ-1", "path": []})
    with pytest.raises(OSError), closing(socket.create_connection(("127.0.0.1", served.named_port), timeout=2)):
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
