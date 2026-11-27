"""How an agent verb reaches a server: its address and token, the JSON reads and writes, and the error a verb raises."""

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.cli.agent_keys import SNAPSHOT_IDENTITY_KEYS
from starpulse.sessions.ports.harness import SessionHarness
lazy from starpulse.runtime.config import ConfigError, discover, load

#: serve's default `--port`, where a server runs unless the caller says otherwise.
DEFAULT_SERVER = "http://localhost:8766"
#: A read the server refuses with a 503 and `Retry-After` is sent again after that wait, at most this many sends in all,
#: each wait capped at `BUSY_PAUSE_MAX_S` seconds: a refusal is a saturated pool, over within moments.
BUSY_SENDS = 4
BUSY_PAUSE_MAX_S = 8
#: A create the server did not answer is sent again under its `request_key`, at most this many sends in all, pausing
#: the server's `retry_after` (`KEYED_PAUSE_S` seconds when it names none, at most `BUSY_PAUSE_MAX_S`) between: the server answers a repeated key with the first send's task and files nothing.
KEYED_SENDS = 4
KEYED_PAUSE_S = 2


class CliError(Exception):
    """A request a verb cannot answer: `code` is one of `_ERROR_EXIT`, the message says why."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra
        """Keys the error document carries beside `error` and `code`."""


def session_harness(config: Path | None = None, transcripts: str | None = None) -> SessionHarness:
    """The harness adapter the config names, the default one's when there is no config; refused when the config is unreadable."""
    try:
        return load(discover(config)).session_harness(transcripts)
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc


class Server(str):
    """A server's address, which formats as the address, carrying the bearer token every request to it sends."""

    token: str
    defaulted: bool
    """True when neither `--server` nor `STARPULSE_URL` named it."""

    def __new__(cls, address: str, token: str = "", defaulted: bool = False) -> Server:
        server = super().__new__(cls, address)
        server.token = token
        server.defaulted = defaulted
        return server

    def refusal(self, status: int, reply: object) -> CliError | None:
        """The error for the default server's 400 with no JSON reply, which is a TLS server refusing plain http when the
        caller never said where the server is; None for any other reply, which keeps its own reason."""
        if status != 400 or not self.defaulted or reply:
            return None
        return CliError(
            "unavailable",
            f"{self} answered 400, a TLS server refusing plain http: STARPULSE_URL is unset, "
            "so set it (export STARPULSE_URL=https://host:port) or pass --server",
        )


def server_url(flag: str | None, environ: Mapping[str, str]) -> Server:
    """The server to read: the `--server` flag, else `STARPULSE_URL`, else the default, without a trailing slash, with
    `STARPULSE_TOKEN` as its bearer token."""
    named = flag or environ.get("STARPULSE_URL")
    return Server((named or DEFAULT_SERVER).rstrip("/"), environ.get("STARPULSE_TOKEN", ""), defaulted=not named)


def auth(base: str) -> dict[str, str]:
    """The headers every request to `base` carries: the `cli` client name, which the server's latency metric labels as
    its caller, and the Authorization bearer token, if any."""
    named = {"X-StarPulse-Client": "cli"}
    return {**named, "Authorization": f"Bearer {base.token}"} if isinstance(base, Server) and base.token else named


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
        # adr-exempt: retry
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
            body = json.load(exc)
        except ValueError:
            body = None
        if isinstance(base, Server) and (refusal := base.refusal(exc.code, body)):
            raise refusal from exc
        return exc.code, body, wait
    except TimeoutError as exc:  # before OSError: a slow search is not an unreachable server
        if path.startswith("/api/search"):
            raise CliError("unavailable", f"slow search at {base}: timed out after 10s") from exc
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def _read_document(base: str, path: str, keys: set[str], noun: str) -> dict[str, Any]:
    """The JSON object the server at `base` answers `path` with; one without every key of `keys` is no StarPulse server."""
    status, document = get(base, path)
    if status != 200:
        raise CliError("unavailable", f"{base} answered {status} for {path.split('?')[0]}: is it a StarPulse server?")
    if not isinstance(document, dict) or not document.keys() >= keys:
        raise CliError("unavailable", f"{base} answered {path.split('?')[0]} with no StarPulse {noun}: is it a StarPulse server?")
    return document


def get_flows(base: str) -> dict[str, Any]:
    """The flows the server at `base` answers: the one stored body, each flow whole with the roles, settled tasks and pull requests a verb reads."""
    return _read_document(base, "/api/flows", {"flows", "roles", "settled", "dags", "error"}, "flows")


def get_runs(base: str) -> dict[str, Any]:
    """The jobs the server at `base` answers: every runs workflow with its latest run, and what the adapter reported."""
    status, document = post(base, "/api/jobs", {})
    if status != 200 or not isinstance(document, dict) or not document.keys() >= {"items", "error"}:
        raise CliError("unavailable", f"{base} answered {status} for /api/jobs: is it a StarPulse server?")
    return document


def flows(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return get_flows(server_url(args.server, environ))


def whole_snapshot(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The `snapshot` verb's document: the whole board, which only a caller that asks for all of it reads."""
    return _read_document(server_url(args.server, environ), "/api/snapshot?view=full", set(SNAPSHOT_IDENTITY_KEYS), "snapshot")


def graphql(base: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """The `data` of `query` run at `/graphql`; a refusal or a GraphQL error is a `CliError`."""
    status, reply = post(base, "/graphql", {"query": query, "variables": variables})
    if status != 200 or not isinstance(reply.get("data"), dict):
        message = "; ".join(str(e.get("message")) for e in reply.get("errors", [])) or f"answered {status}"
        raise CliError("unavailable", f"{base} /graphql: {message}")
    return reply["data"]


def post(base: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return _send("POST", base, path, body)


def put(base: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return _send("PUT", base, path, body)


def delete(base: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    return _send("DELETE", base, path, body)


def _send(method: str, base: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """The status and JSON object the server at `base` answers `method` of `body` to `path` with; {} for any other body.

    A 503 that carries `Retry-After` is the server asking the caller to send the write again, and raises `CliError`
    `unavailable` whose document names `retry_after`, the seconds to wait.
    """
    request = urllib.request.Request(
        f"{base}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **auth(base)},
        method=method,
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=10.0,  # seconds the board writer or the runs adapter may take to answer
        ) as resp:
            return resp.status, _json_or_empty(resp)
    except urllib.error.HTTPError as exc:  # before OSError, which it subclasses
        reply = _json_or_empty(exc)
        if isinstance(base, Server) and (refusal := base.refusal(exc.code, reply)):
            raise refusal from exc
        wait = exc.headers.get("Retry-After", "")
        if exc.code == 503 and wait.isdigit():
            raise CliError("unavailable", str(reply.get("error") or f"{base} answered 503"), retry_after=int(wait)) from exc
        return exc.code, reply
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def put_keyed(base: str, path: str, body: dict[str, Any], key: str | None = None) -> tuple[int, dict[str, Any]]:
    """`put` of a create or edit `body` under `key`, else a fresh `request_key`, sent again with it while the server is unavailable.

    A send that timed out may have applied, so only a repeat under its key is safe: the server answers it with the
    first send's answer. The last send's `CliError` is raised after `KEYED_SENDS` sends. It carries `outcome: unknown`
    when any send failed without showing the write never arrived (a busy refusal and a refused connection do), because
    that send's write may have landed.
    """
    keyed = {**body, "request_key": key or uuid.uuid4().hex}
    landed_maybe = False
    for send in range(1, KEYED_SENDS + 1):
        try:
            return put(base, path, keyed)
        except CliError as unavailable:
            if unavailable.code != "unavailable":
                raise
            cause = unavailable.__cause__
            refused = isinstance(getattr(cause, "reason", cause), ConnectionRefusedError)
            landed_maybe |= "retry_after" not in unavailable.extra and not refused
            if send == KEYED_SENDS:
                if landed_maybe:
                    unavailable.extra["outcome"] = "unknown"
                    unavailable.args = (f"{unavailable}; the write may have landed, so read the task before sending it again",)
                raise
            pause = min(unavailable.extra.get("retry_after", KEYED_PAUSE_S), BUSY_PAUSE_MAX_S)
        # adr-exempt: retry
        time.sleep(pause)
    raise AssertionError("unreachable")


def _json_or_empty(resp: Any) -> dict[str, Any]:
    try:
        document = json.load(resp)
    except ValueError:
        return {}
    return document if isinstance(document, dict) else {}
