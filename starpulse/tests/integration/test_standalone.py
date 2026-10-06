"""The server as a stranger runs it: no `REDIS_URL`, no workspace, one process."""

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
from starpulse.runtime import CONTAINER

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


def _container_exists(runtime: str) -> bool:
    return subprocess.run([runtime, "inspect", CONTAINER], capture_output=True, timeout=30).returncode == 0


@pytest.mark.usefixtures("build")
def test_without_redis_url_or_a_container_runtime_the_server_exits_naming_redis_url(tmp_path: Path) -> None:
    started = time.monotonic()

    result = subprocess.run(
        [sys.executable, "-m", "starpulse.server", "--port", str(_free_port())],
        env=_env(PATH=str(tmp_path)),  # an empty directory: neither docker nor podman resolves
        cwd=tmp_path,  # the board a first serve creates lands here, not in the checkout
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "REDIS_URL" in result.stderr
    assert time.monotonic() - started < 10


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker to start the Valkey container")
@pytest.mark.usefixtures("build")
def test_without_redis_url_the_server_starts_a_valkey_container_and_serves_the_page_and_its_history(
    tmp_path: Path,
) -> None:
    preexisting = _container_exists("docker")
    port = _free_port()
    config = tmp_path / "starpulse.toml"  # the defaults; the history file lands beside it
    config.write_text("")
    proc = subprocess.Popen(
        [sys.executable, "-m", "starpulse.server", "--port", str(port), "--config", str(config)], env=_env()
    )
    try:
        deadline = time.monotonic() + 180  # the first run pulls the Valkey image
        while True:
            assert proc.poll() is None, "the server exited before serving"
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                    assert resp.status == 200
                    break
            except OSError:
                assert time.monotonic() < deadline, "the page never came up"
                time.sleep(0.5)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/history?task=PROJ-1", timeout=5) as resp:
            assert (resp.status, json.loads(resp.read())) == (200, {"task": "PROJ-1", "path": []})
        assert (tmp_path / DEFAULT_FILE).is_file()
        assert (tmp_path / ".starpulse" / "board" / "config.yml").is_file()  # the first serve made its own board
        running = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], capture_output=True, text=True, timeout=30
        )
        assert running.stdout.strip() == "true"
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        if not preexisting:
            subprocess.run(["docker", "rm", "-f", "-v", CONTAINER], capture_output=True, timeout=60)
            subprocess.run(["docker", "volume", "rm", CONTAINER], capture_output=True, timeout=60)
