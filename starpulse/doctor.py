"""The checks behind `starpulse doctor`: whether a StarPulse install can run, each reported as pass or fail with why.

    config        the config file loads
    redis         `REDIS_URL` answers, or a container runtime can start the Valkey the view would use
    server        the server answers `/api/snapshot`
    adapter:<n>   the Board, and each configured runs instance, is producing: it lists tasks or workflows, no error
    gh            the GitHub CLI is installed and logged in, which the pull request reader needs
    stream-lag    no consumer group trails `machine:events` or `runs:events` by more than `MAX_LAG` entries

One failing check never stops the others, so a report names every fault at once. A check that needs a server or Redis
that is down fails too, saying so, rather than vanishing from the list.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import redis
import redis.exceptions

from starpulse import events as machine_events
from starpulse import run_events
from starpulse.config import Config
from starpulse.runtime import CONTAINER, RUNTIMES

#: Entries a consumer group may be behind, delivered but unacknowledged included, before its stream counts as stuck.
MAX_LAG = 100
#: Seconds a `gh` or runtime command may take.
_COMMAND_TIMEOUT = 10
_STREAMS = (machine_events.STREAM, run_events.STREAM)


@dataclass(frozen=True)
class Probes:
    """What the checks touch outside the process: installed tools, commands, and a Redis connection."""

    which: Callable[[str], str | None]
    run: Callable[..., subprocess.CompletedProcess[str]]
    redis: Callable[[str, int, str | None], Any]
    """A client for `host`, `port` and the password (or none)."""


LIVE = Probes(
    which=shutil.which,
    run=subprocess.run,
    redis=lambda host, port, password: redis.Redis(
        host=host,
        port=port,
        password=password,
        socket_connect_timeout=1,  # seconds a down host may keep the check waiting
    ),
)


def _result(check: str, ok: bool, reason: str) -> dict[str, str]:
    return {"check": check, "status": "pass" if ok else "fail", "reason": reason}


def _command(probes: Probes, *argv: str) -> tuple[int, str]:
    """The exit code and trimmed output of `argv`; a command that cannot finish is a failure with its reason."""
    try:
        done = probes.run(list(argv), capture_output=True, text=True, check=False, timeout=_COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout.strip() if done.returncode == 0 else done.stderr.strip())


def _redis(environ: dict[str, str], probes: Probes) -> tuple[dict[str, str], Any]:
    """The `redis` result and a client when there is a Redis to ask; none when a runtime would start one."""
    if url := environ.get("REDIS_URL"):
        parts = urlsplit(url)
        host, port, password = parts.hostname or "127.0.0.1", parts.port or 6379, parts.password
        where = f"REDIS_URL {host}:{port}"
    elif not (runtime := next((r for r in RUNTIMES if probes.which(r)), None)):
        return _result(
            "redis", False, "REDIS_URL is unset and neither docker nor podman is installed; set REDIS_URL to a Redis"
            " or Valkey server (redis://host:6379)"
        ), None  # fmt: skip
    else:
        code, published = _command(probes, runtime, "port", CONTAINER, "6379/tcp")
        if code != 0 or not published:
            return _result(
                "redis", True, f"REDIS_URL is unset; {runtime} starts {CONTAINER} when the server runs"
            ), None
        host, _, text = published.split()[0].replace("0.0.0.0", "127.0.0.1").rpartition(":")
        port, password = int(text), None
        where = f"{CONTAINER} {host}:{port}"
    client = probes.redis(host, port, password or environ.get("REDIS_PASSWORD"))
    try:
        client.ping()
    except redis.exceptions.RedisError as exc:
        return _result("redis", False, f"{where} does not answer: {exc}"), None
    return _result("redis", True, f"{where} answers"), client


def _adapters(snapshot: dict[str, Any] | str, config: Config | str) -> list[dict[str, str]]:
    """One result per producer: the Board, then each configured runs instance."""
    instances = [] if isinstance(config, str) else [i.name for i in config.runs]
    if isinstance(snapshot, str):
        return [_result(f"adapter:{name}", False, "the server is unreachable") for name in ["board", *instances]]
    errors = (snapshot["error"] or "").split("; ")
    board = next(flow for flow in snapshot["flows"] if flow["name"] == "board")
    found = [_board(board, errors)]
    for name in instances:
        error = next((e for e in errors if e.startswith(f"{name}: ")), None)
        listed = sum(dag["name"].startswith(f"{name}/") for dag in snapshot["dags"])
        if error:
            found.append(_result(f"adapter:{name}", False, error))
        elif not listed:
            found.append(_result(f"adapter:{name}", False, f"{name} lists no workflows"))
        else:
            found.append(_result(f"adapter:{name}", True, f"{name} lists {listed} workflows"))
    return found


def _board(board: dict[str, Any], errors: list[str]) -> dict[str, str]:
    if reading := next((e for e in errors if e.startswith("board: ")), None):
        return _result("adapter:board", False, reading)
    return _result("adapter:board", True, f"{len(board['agents'])} open tasks")


def _gh(probes: Probes) -> dict[str, str]:
    if not probes.which("gh"):
        return _result("gh", False, "gh is not installed, so a task's pull requests carry no state")
    code, text = _command(probes, "gh", "auth", "status")
    if code != 0:
        return _result("gh", False, f"gh auth status failed: {text}; run `gh auth login`")
    return _result("gh", True, "gh is logged in")


def _lag(redis_ok: bool, client: Any) -> dict[str, str]:
    if client is None:
        reason = "no Redis is running yet, so no stream can lag" if redis_ok else "Redis is unreachable"
        return _result("stream-lag", redis_ok, reason)
    worst, groups = 0, 0
    try:
        for stream in _STREAMS:
            try:
                found = client.xinfo_groups(stream)
            except redis.exceptions.ResponseError:  # the stream does not exist yet
                continue
            for group in found:
                behind = (group.get("lag") or 0) + group.get("pending", 0)
                if behind > MAX_LAG:
                    return _result(
                        "stream-lag",
                        False,
                        f"{stream} group {group['name']} is {behind} entries behind (limit {MAX_LAG})",
                    )
                worst, groups = max(worst, behind), groups + 1
    except redis.exceptions.RedisError as exc:
        return _result("stream-lag", False, f"cannot read the consumer groups: {exc}")
    return _result("stream-lag", True, f"{groups} consumer groups, the furthest {worst} entries behind")


def run_checks(
    snapshot: dict[str, Any] | str, config: Config | str, environ: dict[str, str], probes: Probes, server: str
) -> dict[str, Any]:
    """Every check as `{ok, checks: [{check, status, reason}]}`.

    `snapshot` is the server's snapshot, or the reason it could not be read; `config` is the loaded config, or the
    reason it could not be loaded; `server` is the address the snapshot was read from."""
    redis_result, client = _redis(environ, probes)
    checks = [
        _result(
            "config", *((False, config) if isinstance(config, str) else (True, f"{len(config.runs)} runs instances"))
        ),
        redis_result,
        _result("server", *((False, snapshot) if isinstance(snapshot, str) else (True, f"{server} answers"))),
        *_adapters(snapshot, config),
        _gh(probes),
        _lag(redis_result["status"] == "pass", client),
    ]
    return {"ok": all(c["status"] == "pass" for c in checks), "checks": checks}
