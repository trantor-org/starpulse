"""Where the view's Redis comes from.

`REDIS_URL` names a Redis or Valkey server. With it unset and Docker or Podman installed, the view starts
one named Valkey container with a volume on the first run and reuses it after. With neither, it refuses and
names `REDIS_URL` rather than retrying a connection nothing will answer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, MutableMapping, Sequence

import redis.exceptions

from starpulse import events as machine_events
from starpulse import run_events
from starpulse.streams import endpoint_from_url

#: The container and its volume; a named volume keeps the stream across restarts.
CONTAINER = "flow-view-valkey"
IMAGE = "valkey/valkey:8"
#: The streams StarPulse itself reads; a board adapter names its own beside them.
_PREFIXES = (
    machine_events.REDIS_ENV_PREFIX,
    run_events.REDIS_ENV_PREFIX,
)
RUNTIMES = ("docker", "podman")
#: Seconds a runtime command may take; `run` may pull the image, so the bound is generous.
_COMMAND_TIMEOUT = 120


class RedisUnavailableError(RuntimeError):
    """No Redis can be reached or started; the message names `REDIS_URL`."""


def _ping(host: str, port: int) -> bool:  # pragma: no mutate block — a live socket
    try:
        return bool(redis.Redis(host=host, port=port, socket_connect_timeout=1).ping())
    except redis.exceptions.RedisError:
        return False


def apply_url(url: str, environ: MutableMapping[str, str], prefixes: Sequence[str] = ()) -> None:
    """Point every stream the view reads, and each of `prefixes`, at `url`; its password, when it has one, becomes
    `REDIS_PASSWORD` and its user `REDIS_USERNAME`, both decoded, and a `rediss://` URL sets `REDIS_SSL`."""
    endpoint = endpoint_from_url(url)
    for prefix in (*_PREFIXES, *prefixes):
        environ[f"{prefix}_REDIS_HOST"] = endpoint["redis_host"]
        environ[f"{prefix}_REDIS_PORT"] = str(endpoint["redis_port"])
    if endpoint["redis_username"]:
        environ["REDIS_USERNAME"] = endpoint["redis_username"]
    if endpoint["redis_password"]:
        environ["REDIS_PASSWORD"] = endpoint["redis_password"]
    if endpoint["redis_ssl"]:
        environ["REDIS_SSL"] = "1"


def _refuse(why: str) -> RedisUnavailableError:
    return RedisUnavailableError(f"{why}; set REDIS_URL to a Redis or Valkey server (redis://host:6379)")


def _start_container(runtime: str, run: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    """Create or start `CONTAINER` and return the loopback `host:port` it answers on."""

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return run([runtime, *args], capture_output=True, text=True, check=False, timeout=_COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise _refuse(f"{runtime} {args[0]} timed out after {_COMMAND_TIMEOUT} s") from None

    state = call("inspect", "-f", "{{.State.Running}}", CONTAINER)
    if state.returncode != 0:
        started = call(
            "run", "-d", "--name", CONTAINER, "-v", f"{CONTAINER}:/data", "-p", "127.0.0.1::6379", IMAGE,
            "valkey-server", "--appendonly", "yes",
        )  # fmt: skip
    elif state.stdout.strip() != "true":
        started = call("start", CONTAINER)
    else:
        started = state
    if started.returncode != 0:
        raise _refuse(f"{runtime} could not start {CONTAINER}: {started.stderr.strip()}")
    # A restarted container may publish a different ephemeral port, so ask every run.
    port = call("port", CONTAINER, "6379/tcp")
    if port.returncode != 0 or not (published := port.stdout.split()):
        raise _refuse(f"{runtime} reports {CONTAINER} publishes no port: {port.stderr.strip()}")
    return published[0].replace("0.0.0.0", "127.0.0.1")


def ensure_redis(
    environ: MutableMapping[str, str] = os.environ,
    *,
    prefixes: Sequence[str] = (),
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ping: Callable[[str, int], bool] = _ping,
    ready_timeout: float = 20.0,
) -> None:
    """Make `environ` reach one Redis: `REDIS_URL` when set, otherwise the Valkey container.

    `prefixes` are a board adapter's stream names, pointed at the same Redis."""
    if url := environ.get("REDIS_URL"):
        apply_url(url, environ, prefixes)
        return
    if not (runtime := next((r for r in RUNTIMES if which(r)), None)):
        raise _refuse("REDIS_URL is unset and neither docker nor podman is installed")
    host, _, port = _start_container(runtime, run).rpartition(":")
    deadline = time.monotonic() + ready_timeout
    while not ping(host, int(port)):
        if time.monotonic() >= deadline:
            raise _refuse(f"{CONTAINER} did not answer on {host}:{port} within {ready_timeout:g} s")
        time.sleep(0.2)
    environ["REDIS_URL"] = f"redis://{host}:{port}"
    apply_url(environ["REDIS_URL"], environ, prefixes)
