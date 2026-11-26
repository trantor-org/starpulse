"""`starpulse incident open <type> <key>`: tell the sessions of a shared fault over NATS and hold its owner task."""

import argparse
import asyncio
import json
import time
from collections.abc import Mapping
from typing import Any

import nats
from nats.errors import Error as NatsError

from starpulse.board.model.view import board_flow, roles_of
from starpulse.bridge.reach import Reach
from starpulse.bridge.subjects import token, wake_subject
from starpulse.cli import agent_wire
from starpulse.cli.agent_subscribe import bridge
from starpulse.cli.agent_tasks import record_call, task_dispatch, task_park, writer
from starpulse.sessions.identity import same_session

_TIMEOUT_S = 5.0


def _publish(url: str, subject: str, body: bytes, wake: str = "") -> None:
    """One core NATS publish, flushed so it left this process; no stream or consumer is needed, so it works whenever
    the server listens, with StarPulse's API down. With `wake`, an empty message follows on that subject over the same
    connection, so the bridge's delivery looks for the incident once it is stored."""

    async def send() -> None:
        client = await nats.connect(url, connect_timeout=_TIMEOUT_S, allow_reconnect=False)
        try:
            await client.publish(subject, body)
            if wake:
                await client.publish(wake)
            await client.flush(timeout=_TIMEOUT_S)
        finally:
            await client.close()

    try:
        asyncio.run(send())
    except (NatsError, OSError, TimeoutError) as exc:
        raise agent_wire.CliError("unavailable", f"the NATS server did not answer: {exc}") from exc


def _open_owner(snapshot: dict[str, Any], source: str) -> dict[str, Any] | None:
    """The open task filed under `source`, or None when the board has none."""
    done = roles_of(snapshot).done
    return next((a for a in board_flow(snapshot)["agents"] if a.get("source") == source and a["state"] != done), None)


def _hits_failure(snapshot: dict[str, Any], agent: dict[str, Any]) -> bool:
    pulls = [*snapshot.get("pulls", {}).get(agent["id"], ()), *agent.get("pulls", ())]
    return any(p.get("checks") == "failing" and not (p.get("merged") or p.get("closed")) for p in pulls)


def _wait_on_owner(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    snapshot: dict[str, Any],
    reach: Reach,
    owner: str,
    source: str,
    session: str,
    failing_pull: bool = False,
) -> tuple[list[str], dict[str, str]]:
    """Park each held task in `reach` on `owner`, which releases it when Done: the tasks now waiting and, by task, why
    another was refused. The owner, the finder's own task and a task no session holds never wait; a session is told by
    the task's move on its consumer and by the park's comment on the task. With `failing_pull`, only a task with an open
    pull request whose checks read failing waits: the one that hit the failure."""
    waiting: list[str] = []
    refused: dict[str, str] = {}
    comment = f"Waiting on {owner}: {source} reaches this task; it is released when {owner} is Done."
    for agent in board_flow(snapshot)["agents"]:
        holder = agent.get("assignee") or ""
        if agent["id"] == owner or holder in ("", "released") or same_session(holder, session):
            continue
        if not reach.covers(agent, roles_of(snapshot).working):
            continue
        if failing_pull and not _hits_failure(snapshot, agent):
            continue
        park = argparse.Namespace(
            **{
                **vars(args),
                "task": agent["id"],
                "until_task": [owner],
                "until": [],
                "operator": "",
                "comment": comment,
            }
        )
        try:
            answer = task_park(park, environ)
        except agent_wire.CliError as exc:
            refused[agent["id"]] = str(exc)
            continue
        if answer["ok"]:
            waiting.append(agent["id"])
        else:
            refused[agent["id"]] = answer["reason"]
    return waiting, refused


def _description(source: str) -> str:
    return (
        f"## Outcome\n\nThe shared fault `{source}` is fixed or its owner is named.\n\n"
        "## Why\n\nA session found a fault that blocks others; sessions it blocks wait on this task.\n\n"
        f"## Current State\n\nThe fault is open under `{source}`.\n\n"
        "## Scope\n\n- Find the cause and fix it, or file the task that does.\n\n"
        "## Out of Scope\n\n- Work the fault does not block.\n\n"
        "## Blast Radius\n\nreach 1 · data 0 · undo 0 · detect 0. Sessions the fault blocks stay waiting.\n\n"
        "## Stop Conditions\n\n- The cause lies outside this network.\n"
    )


def _create_and_dispatch(args: argparse.Namespace, environ: Mapping[str, str], source: str) -> str:
    base, path = agent_wire.server_url(args.server, environ), "/api/tasks"
    body = {
        "title": f"Incident {args.type} {args.key}",
        "description": _description(source),
        "profile": "@agent-standard-high",
        "labels": ["incident"],
        "type": "bug",
        "source": source,
        **writer(args, environ),
    }
    status, reply = agent_wire.put(base, path, body)
    task = record_call(base, path, status, reply, ok=(201,))["task"]
    _dispatch(args, environ, task)
    return task


def _dispatch(args: argparse.Namespace, environ: Mapping[str, str], task: str) -> None:
    dispatched = task_dispatch(argparse.Namespace(**{**vars(args), "task": task, "replaces": ""}), environ)
    if not dispatched["ok"]:
        raise agent_wire.CliError("refused", f"the incident task {task} was not dispatched to: {dispatched['reason']}")


def open_incident(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Publish `incident.<type>.<key>` to NATS and open the owner task the finder holds.

    One owner task per type and key: a task another session holds is joined, and nothing is published again. With
    `--owner` that task is the owner and none is created or dispatched to. The tasks
    the type's `[bridge.incidents.<type>]` reach covers wait on the owner task. While the
    board is down the publish still goes out and `task` is null; rerun once it returns to create the task, which finds
    the open one when a finder already did. A NATS server that does not answer fails the command only when the board
    did not answer either; with the owner task held the answer says `published` false, and the finder's own rerun
    publishes again, with the task.
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
    waiting: list[str] = []
    refused: dict[str, str] = {}
    try:
        snapshot = agent_wire.flows(args, environ)
        given = None
        if args.owner:
            given = next(
                (
                    a
                    for a in board_flow(snapshot)["agents"]
                    if a["id"].casefold() == args.owner.casefold() and a["state"] != roles_of(snapshot).done
                ),
                None,
            )
            if given is None:
                raise agent_wire.CliError("refused", f"--owner {args.owner} is not an open task")
        owner = None if args.owner else _open_owner(snapshot, source)
        if owner and owner.get("assignee") and not same_session(owner["assignee"], session):
            return {"subject": source, "task": owner["id"], "holder": owner["assignee"], "published": False}
        if owner and not owner.get("assignee"):
            try:
                _dispatch(args, environ, owner["id"])
            except agent_wire.CliError as exc:
                if exc.code != "refused":
                    raise
                now = _open_owner(agent_wire.flows(args, environ), source)
                if not (now and now.get("assignee") and not same_session(now["assignee"], session)):
                    raise
                return {"subject": source, "task": now["id"], "holder": now["assignee"], "published": False}
        task = given["id"] if given else owner["id"] if owner else _create_and_dispatch(args, environ, source)
        if reach := config.incidents.get(kind):
            waiting, refused = _wait_on_owner(args, environ, snapshot, reach, task, source, session, args.failing_pull)
    except agent_wire.CliError as exc:
        if exc.code != "unavailable":
            raise
    body: dict[str, Any] = {"type": kind, "key": key, "finder": session, "task": task, "at": int(time.time())}
    if args.failing_pull:
        holders = {a["id"]: a.get("assignee") or "" for a in board_flow(snapshot)["agents"]} if waiting else {}
        body["parked"] = [token(holders[t]) for t in waiting]
    try:
        _publish(f"nats://127.0.0.1:{config.port}", source, json.dumps(body).encode(), wake_subject(config.board))
        published = True
    except agent_wire.CliError:
        if task is None:
            raise
        published = False
    return {
        "subject": source,
        "task": task,
        "holder": session if task and not args.owner else "",
        "published": published,
        "waiting": waiting,
        "refused": refused,
    }
