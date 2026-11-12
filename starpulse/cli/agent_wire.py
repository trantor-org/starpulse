"""How an agent verb reaches a server: its address and token, the JSON reads and writes, and the error a verb raises."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from starpulse.cli.agent_keys import NEWER_SNAPSHOT_KEYS, SNAPSHOT_KEYS

#: serve's default `--port`, where a server runs unless the caller says otherwise.
DEFAULT_SERVER = "http://localhost:8766"
#: A read the server refuses with a 503 and `Retry-After` is sent again after that wait, at most this many sends in all,
#: each wait capped at `BUSY_PAUSE_MAX_S` seconds: a refusal is a saturated pool, over within moments.
BUSY_SENDS = 4
BUSY_PAUSE_MAX_S = 8


class CliError(Exception):
    """A request a verb cannot answer: `code` is one of `_ERROR_EXIT`, the message says why."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra
        """Keys the error document carries beside `error` and `code`."""


class Server(str):
    """A server's address, which formats as the address, carrying the bearer token every request to it sends."""

    token: str

    def __new__(cls, address: str, token: str = "") -> Server:
        server = super().__new__(cls, address)
        server.token = token
        return server


def server_url(flag: str | None, environ: Mapping[str, str]) -> Server:
    """The server to read: the `--server` flag, else `STARPULSE_URL`, else the default, without a trailing slash, with
    `STARPULSE_TOKEN` as its bearer token."""
    address = (flag or environ.get("STARPULSE_URL") or DEFAULT_SERVER).rstrip("/")
    return Server(address, environ.get("STARPULSE_TOKEN", ""))


def auth(base: str) -> dict[str, str]:
    """The Authorization header `base` carries, if any."""
    return {"Authorization": f"Bearer {base.token}"} if isinstance(base, Server) and base.token else {}


def _open_get(request: urllib.request.Request, timeout: float) -> Any:
    """The response to a GET, sent once more when the server closed the connection before any byte (an empty reply, as
    a restart does to a request it had taken); a second empty reply, and any other failure, raises."""
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except ConnectionResetError:  # `RemoteDisconnected` is one; a refused connection is not
        return urllib.request.urlopen(request, timeout=timeout)


def get(base: str, path: str, timeout: float = 10.0) -> tuple[int, Any]:
    """The status and JSON body the server at `base` answers `path` with; None for a body that is no JSON. `timeout`
    is the seconds the server may take to answer; an empty reply is sent once more, and a 503 that carries
    `Retry-After` is waited out and sent again, up to `BUSY_SENDS` sends."""
    for send in range(1, BUSY_SENDS + 1):
        status, document, wait = _get_once(base, path, timeout)
        if status != 503 or not wait.isdigit() or send == BUSY_SENDS:
            return status, document
        time.sleep(min(int(wait), BUSY_PAUSE_MAX_S))
    raise AssertionError("unreachable")


def _get_once(base: str, path: str, timeout: float) -> tuple[int, Any, str]:
    """One read's status, JSON body and `Retry-After` header (empty when absent)."""
    try:
        with _open_get(urllib.request.Request(f"{base}{path}", headers=auth(base)), timeout) as resp:
            return resp.status, json.load(resp), ""
    except urllib.error.HTTPError as exc:
        wait = exc.headers.get("Retry-After", "") if exc.headers else ""
        try:
            return exc.code, json.load(exc), wait
        except ValueError:
            return exc.code, None, wait
    except TimeoutError as exc:  # before OSError: a slow search is not an unreachable server
        if path.startswith("/api/search"):
            raise CliError("unavailable", f"slow search at {base}: timed out after 10s") from exc
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def get_snapshot(base: str) -> dict[str, Any]:
    """The snapshot the server at `base` answers; JSON without every snapshot key a server of the last release serves is no StarPulse server."""
    path = "/api/snapshot"
    status, document = get(base, f"{path}?view=full")
    if status != 200:
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    if not isinstance(document, dict) or not document.keys() >= set(SNAPSHOT_KEYS) - set(NEWER_SNAPSHOT_KEYS):
        raise CliError("unavailable", f"{base} answered {path} with no StarPulse snapshot: is it a StarPulse server?")
    return document


def snapshot(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return get_snapshot(server_url(args.server, environ))


def post(base: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """The status and JSON object the server at `base` answers a POST of `body` to `path` with; {} for any other body.

    A 503 that carries `Retry-After` is the server asking the caller to send the write again, and raises `CliError`
    `unavailable` whose document names `retry_after`, the seconds to wait.
    """
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **auth(base)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=10.0,  # seconds the board writer or the runs adapter may take to answer
        ) as resp:
            return resp.status, _json_or_empty(resp)
    except urllib.error.HTTPError as exc:  # before OSError, which it subclasses
        reply = _json_or_empty(exc)
        wait = exc.headers.get("Retry-After", "")
        if exc.code == 503 and wait.isdigit():
            raise CliError("unavailable", str(reply.get("error") or f"{base} answered 503"), retry_after=int(wait)) from exc
        return exc.code, reply
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def _json_or_empty(resp: Any) -> dict[str, Any]:
    try:
        document = json.load(resp)
    except ValueError:
        return {}
    return document if isinstance(document, dict) else {}
