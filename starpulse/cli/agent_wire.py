"""How an agent verb reaches a server: its address and token, the JSON reads and writes, and the error a verb raises."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from starpulse.cli.agent_keys import NEWER_SNAPSHOT_KEYS, SNAPSHOT_KEYS

#: serve's default `--port`, where a server runs unless the caller says otherwise.
DEFAULT_SERVER = "http://localhost:8766"


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


def get(base: str, path: str) -> tuple[int, Any]:
    """The status and JSON body the server at `base` answers `path` with; None for a body that is no JSON."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{base}{path}", headers=auth(base)),
            timeout=10.0,  # seconds the server may take to answer one read
        ) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, None
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
