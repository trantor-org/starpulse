"""`starpulse incident open <type> <key>`: tell the sessions of a shared fault over NATS and hold its owner task."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping
from typing import Any

import nats
from nats.errors import Error as NatsError

from starpulse.board.adapters.session_activity import same_holder
from starpulse.board.model.view import board_flow, roles_of
from starpulse.bridge.subjects import token
from starpulse.cli import agent_wire
from starpulse.cli.agent_subscribe import bridge
from starpulse.cli.agent_tasks import record_call, task_claim, writer

_TIMEOUT_S = 5.0


def _publish(url: str, subject: str, body: bytes) -> None:
    """One core NATS publish, flushed so it left this process; no stream or consumer is needed, so it works whenever
    the server listens, with StarPulse's API down."""

    async def send() -> None:
        client = await nats.connect(url, connect_timeout=_TIMEOUT_S, allow_reconnect=False)
        try:
            await client.publish(subject, body)
            await client.flush(timeout=_TIMEOUT_S)
        finally:
            await client.close()

    try:
        asyncio.run(send())
    except (NatsError, OSError, TimeoutError) as exc:
        raise agent_wire.CliError("unavailable", f"the NATS server did not answer: {exc}") from exc


def _open_owner(args: argparse.Namespace, environ: Mapping[str, str], source: str) -> dict[str, Any] | None:
    """The open task filed under `source`, or None when the board has none; raises `unavailable` while it is down."""
    snapshot = agent_wire.snapshot(args, environ)
    done = roles_of(snapshot).done
    return next((a for a in board_flow(snapshot)["agents"] if a.get("source") == source and a["state"] != done), None)


def _create_and_claim(args: argparse.Namespace, environ: Mapping[str, str], source: str) -> str:
    base, path = agent_wire.server_url(args.server, environ), "/api/tasks"
    body = {
        "title": f"Incident {args.type} {args.key}",
        "description": f"A shared fault, `{source}`, found by a session; sessions it blocks wait on this task.",
        "labels": ["incident"],
        "type": "bug",
        "source": source,
        **writer(args, environ),
    }
    status, reply = agent_wire.post(base, path, body)
    task = record_call(base, path, status, reply, ok=(201,))["task"]
    _claim(args, environ, task)
    return task


def _claim(args: argparse.Namespace, environ: Mapping[str, str], task: str) -> None:
    claimed = task_claim(argparse.Namespace(**{**vars(args), "task": task}), environ)
    if not claimed["ok"]:
        raise agent_wire.CliError("refused", f"the incident task {task} was not claimed: {claimed['reason']}")


def open_incident(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Publish `incident.<type>.<key>` to NATS and open the owner task the finder holds.

    One owner task per type and key: a task another session holds is joined, and nothing is published again. While the
    board is down the publish still goes out and `task` is null; rerun once it returns to create the task, which finds
    the open one when a finder already did. The finder's own rerun publishes again, with the task, so a publish that
    failed after the task was made is not lost.
    """
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise agent_wire.CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    kind, key = token(args.type), token(args.key)
    if not (kind and key):
        raise agent_wire.CliError("refused", "an incident's type and key each need a letter, digit, `_` or `-`")
    source = f"incident.{kind}.{key}"
    config = bridge(args)
    task: str | None = None
    try:
        owner = _open_owner(args, environ, source)
        if owner and owner.get("assignee") and not same_holder(owner["assignee"], session):
            return {"subject": source, "task": owner["id"], "holder": owner["assignee"], "published": False}
        if owner and not owner.get("assignee"):
            _claim(args, environ, owner["id"])
        task = owner["id"] if owner else _create_and_claim(args, environ, source)
    except agent_wire.CliError as exc:
        if exc.code != "unavailable":
            raise
    body = {"type": kind, "key": key, "finder": session, "task": task, "at": int(time.time())}
    _publish(f"nats://127.0.0.1:{config.port}", source, json.dumps(body).encode())
    return {"subject": source, "task": task, "holder": session if task else "", "published": True}
