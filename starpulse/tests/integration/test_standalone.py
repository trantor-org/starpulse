"""The server as a stranger runs it: no Redis, no container runtime, no workspace, one process."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from starpulse import server
from starpulse.history import DEFAULT_FILE

_ENV_DROPPED = ("REDIS_URL", "REDIS_PASSWORD", "DATABASE_URI")


@pytest.fixture
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
    env = {k: v for k, v in os.environ.items() if k not in _ENV_DROPPED and not k.endswith("_REDIS_HOST")}
    return env | overrides


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return resp.status, json.loads(resp.read())


@pytest.mark.usefixtures("build")
def test_without_redis_or_any_tool_on_the_path_the_server_serves_the_page_its_history_and_what_emit_pushed(
    tmp_path: Path,
) -> None:
    port = _free_port()
    config = tmp_path / "starpulse.toml"  # the defaults; the history file lands beside it
    config.write_text("")
    env = _env(PATH=str(tmp_path))  # an empty directory: no docker, podman or gh resolves, and no Redis answers
    proc = subprocess.Popen(
        [sys.executable, "-m", "starpulse.server", "--port", str(port), "--config", str(config)], env=env
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            assert proc.poll() is None, "the server exited before serving"
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                    assert resp.status == 200
                    break
            except OSError:
                assert time.monotonic() < deadline, "the page never came up"
                time.sleep(0.2)
        assert _get(port, "/api/history?task=PROJ-1") == (200, {"task": "PROJ-1", "path": []})
        assert (tmp_path / DEFAULT_FILE).is_file()
        assert (tmp_path / ".starpulse" / "board" / "config.yml").is_file()  # the first serve made its own board

        emitted = subprocess.run(
            [
                sys.executable,
                "-m",
                "starpulse",
                "emit",
                "start",
                "--workflow",
                "nightly",
                "--run",
                "r1",
                "--status",
                "running",
                "--config",
                str(config),
            ],  # fmt: skip
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert emitted.returncode == 0, emitted.stderr
        deadline = time.monotonic() + 30
        while "pushed/nightly" not in [d["name"] for d in _get(port, "/api/snapshot")[1]["dags"]]:
            assert proc.poll() is None, "the server exited"
            assert time.monotonic() < deadline, "the emitted run never reached the snapshot"
            time.sleep(0.2)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
