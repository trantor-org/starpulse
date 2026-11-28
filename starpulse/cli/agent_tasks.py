"""The board, task, milestone, doc and search verbs of `starpulse ... --agent`: reads and writes of the board's records."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from starpulse.board.model.plain_text import render as render_text
from starpulse.board.model.seam import OPERATOR
from starpulse.board.model.view import AGENT, board_columns, board_flow, cold_agent, done_ids, roles_of, task_view
from starpulse.cli import agent_wire, step_times
from starpulse.cli.agent_keys import LIFECYCLE_KEYS
from starpulse.github.model.pulls import cited_pull
from starpulse.machine_engine.model.transitions import ARCHIVED, lane_id
from starpulse.sessions.harness import DEFAULT, configured
from starpulse.sessions.identity import same_session
from starpulse.sessions.ports.harness import SessionHarness
lazy from starpulse.board.model.markdown import MarkdownRefusedError, imported
lazy from starpulse.board.model.markdown import render as render_markdown

#: What a task route's 404 says when the board has no such task, as opposed to a board that cannot read or write tasks.
_TASK_MISSING = ("is not on the board", "has no record to read")

#: Each `task edit` flag's destination and the record field it sets, in the order `changed` reports them.
_TASK_EDIT_FIELDS = {
    "title": "title",
    "type": "type",
    "priority": "priority",
    "impact": "impact",
    "urgency": "urgency",
    "tier": "tier",
    "profile": "profile",
    "milestone": "milestone",
    "source": "source",
    "follows": "follows",
    "label": "labels",
    "dependency": "dependencies",
    "status": "status",
    "reference": "references",
    "documentation": "documentation",
    "modified_file": "modifiedFiles",
    "description": "description",
    "plan": "plan",
    "notes": "notes",
    "final_summary": "finalSummary",
    "members": "members",
}
#: The change-only keys of an edit (`EXTRA["edit"]`, kept here so the CLI loads no pydantic): no base value.
_UNBASED = frozenset({"appendNotes", "planReason"})
#: The checklists `task edit` changes: each record field's flag key (`--ac`, `--reword-ac`, ...) and the name a refusal gives it.
_CHECKLISTS = {"acceptanceCriteria": ("ac", "Acceptance Criteria"), "definitionOfDone": ("dod", "Definition of Done")}
#: A checklist's flag destinations, as `{}` stands for its key: add, reword, remove, check and uncheck.
_CHECKLIST_DESTS = ("{}", "reword_{}", "remove_{}", "check_{}", "uncheck_{}")


def board(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = agent_wire.flows(args, environ)
    states = board_flow(snapshot)["machine"]["states"]
    if args.state and args.state not in (ids := [s["id"] for s in states]):
        raise agent_wire.CliError("usage", f"unknown state {args.state}; the board has {', '.join(ids)}")

    legacy = (args.assignee or "").startswith("@")  # `--assignee` named the profile before it named the session
    profile, session = args.profile or (args.assignee if legacy else None), None if legacy else args.assignee

    def kept(agent: dict[str, Any]) -> bool:
        return (
            (not args.milestone or agent["milestone"] == args.milestone)
            and (not args.type or agent.get("type", "") == args.type)
            and (not args.label or args.label in agent["labels"])
            and (not profile or agent["model"] == profile)
            and (not session or same_session(agent.get("assignee"), session))
        )

    board = board_columns(snapshot, kept, args.state)
    harness = configured(DEFAULT, os.environ)
    views = [_active(task, snapshot, harness) for column in board["columns"] for task in column["tasks"]]
    settled = iter(_without_done_dependencies(agent_wire.server_url(args.server, environ), views))
    for column in board["columns"]:
        column["tasks"] = [next(settled) for _ in column["tasks"]]
    finished = roles_of(snapshot).done
    # an unfiltered board skips the cold pages (a request per hundred Done tasks); a milestone or the done state asks for them, unless `--no-cold`
    if finished and args.state in (None, finished) and (args.state or args.milestone) and not args.no_cold:
        done = done_ids(snapshot)
        column = next(column for column in board["columns"] if column["state"] == finished)
        bare = {"milestone": "", "labels": [], "dependencies": [], "prs": [], "moves": {}}
        cards = [bare | card for card in _cold_done(agent_wire.server_url(args.server, environ), args.milestone, args.limit)]
        column["tasks"] += [task_view(card, snapshot, done) for card in cards if kept(card)]
    return board


_FINISHED = "query Finished($ids: [ID!]!) { finished(ids: $ids) }"

#: Done tasks one `/api/done` request asks for.
_COLD_PAGE = 100


def _cold_done(base: str, milestone: str | None, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Every done task past its hot day, of `milestone` when given, as a board card, newest first; the snapshot lists
    them by id only. `limit` asks one page of that many and stops there."""
    before = ""
    asked = f"&milestone={urllib.parse.quote(milestone, safe='')}" if milestone else ""
    while True:
        status, page = agent_wire.get(base, f"/api/done?limit={limit or _COLD_PAGE}{asked}{before}")
        if status != 200:
            raise agent_wire.CliError(
                "unavailable", f"{base} answered {status} for /api/done: cannot list the done tasks"
            )
        yield from page["tasks"]
        if limit or not page["more"]:
            return
        before = f"&before={page['tasks'][-1]['entered']}"


# Code, an existing link or a bare URL is kept as written; only a bare id outside them is linked.
# A three-digit floor and the `] ` guard keep a criterion's `- [ ] #N` index unlinked.
_LINKABLE = re.compile(
    r"(?P<kept>```.*?```|`[^`\n]*`|\[[^\]]*\]\([^)]*\)|https?://\S+)"
    r"|\b(?P<task>TASK-\d+)\b|(?<![\w/&])(?<!\] )#(?P<pull>\d{3,})\b",
    re.DOTALL,
)


def linkify(text: str, base: str, pulls: Sequence[Mapping[str, Any]] = ()) -> str:
    """`text` with each bare `TASK-N` linked to its card on the Board at `base`, and each `#N` to the task's pull
    request whose link ends `/pull/N`. A `#N` no pull request of the task has is left bare."""
    urls = {url.rsplit("/", 1)[-1]: url for url in (pull["url"] for pull in pulls)}

    def link(match: re.Match[str]) -> str:
        if task := match["task"]:
            return f"[{task}]({base.rstrip('/')}/?view=kanban&task={task})"
        if (pull := match["pull"]) and pull in urls:
            return f"[#{pull}]({urls[pull]})"
        return match[0]

    return _LINKABLE.sub(link, text)


def _keyed(view: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """`view` with its item's UUID as `id` beside the `key` it was named by; `id` is empty for a task the board holds no record of."""
    return {**view, "id": document.get("id", ""), "key": view["id"]}


def _described(view: dict[str, Any], description: str, base: str) -> dict[str, Any]:
    """`view` with the task's `description`, its ids linked."""
    return {**view, "description": linkify(description, base, view["prs"])}


def _carrier(base: str, task_id: str) -> str | None:
    """The id of the task whose file lists `task_id` as an alias (an id it was renamed from);
    None when `task_id` is a task's own id or no task carries it."""
    status, document = agent_wire.get(base, f"/api/task/{urllib.parse.quote(task_id, safe='')}")
    held = str(document.get("record", {}).get("id") or "") if status == 200 else ""
    return None if held.casefold() in {"", task_id.casefold()} else held


_MOVES = "query($id: ID!) { task(id: $id) { moves { to allowed reason skill writers actors { actor allowed reason skill } } } }"


def _read_moves(base: str, task_id: str) -> dict[str, dict[str, Any]]:
    """The board's verdict on each column for a task whose stored card carries none, in the shape a snapshot card holds."""
    listed = agent_wire.graphql(base, _MOVES, {"id": task_id})["task"]["moves"]
    return {
        move["to"]: {
            **{key: move[key] for key in ("allowed", "reason", "skill", "writers")},
            "actors": {actor["actor"]: {key: actor[key] for key in ("allowed", "reason", "skill")} for actor in move["actors"]},
        }
        for move in listed
    }


def show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    if getattr(args, "markdown", False):
        return {"task": args.task, "markdown": render_markdown(_read_record(args, environ))}
    if getattr(args, "text", False):
        document = _read_document(args, environ)
        record = document["record"]
        done = lane_id(record["status"]) == document["done"]
        if document.get("archived") and not done:
            # The archived file keeps the status and holder it had when archived; the lane is archived and none holds it.
            record = {**record, "status": "Archived", "assignee": ""}
        return {"task": args.task, "text": render_text(record, done=done)}
    snapshot = agent_wire.flows(args, environ)
    wanted = args.task.casefold()
    agents = {agent["id"].casefold(): agent for agent in board_flow(snapshot)["agents"]}
    if (agent := agents.get(wanted)) is None:
        if carrier := _carrier(agent_wire.server_url(args.server, environ), args.task):
            return show(argparse.Namespace(**{**vars(args), "task": carrier}), environ)
        return _show_cold(agent_wire.server_url(args.server, environ), args.task, snapshot)
    base = agent_wire.server_url(args.server, environ)
    if agent["state"] == roles_of(snapshot).done and "description" not in agent:
        return _show_cold(base, agent["id"], snapshot)
    path = f"/api/task/{urllib.parse.quote(agent['id'], safe='')}"
    status, reply = agent_wire.get(base, path)
    # a task only the snapshot holds has no record, so no plan; any other failure is the caller's to see
    record = {} if status == 404 else record_call(base, path, status, reply).get("record", {})
    if record:  # the file holds an edit before the snapshot does, and a follow-up edit takes its base from this read
        agent = {
            **agent,
            "state": lane_id(record["status"]),
            **{field: record[field] for field in ("title", "milestone", "labels", "dependencies")},
        }
    if "moves" not in agent:  # a stored card leaves its moves to the board's verdicts
        agent = {**agent, "moves": _read_moves(base, agent["id"])}
    if "description" not in agent:  # a stored card leaves its detail to the record
        agent = {
            **agent,
            "description": record.get("description", ""),
            "criteria": [
                {"text": item["text"], "checked": item["checked"]} for item in record.get("acceptanceCriteria") or []
            ],
        }
    (view,) = _without_done_dependencies(base, [task_view(agent, snapshot)])
    shown = _described(_keyed(_active(view, snapshot, configured(DEFAULT, os.environ)), reply if record else {}), agent["description"], base)
    return {**shown, "members": record.get("members") or {}}


def _without_done_dependencies(base: str, views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`views` with each dependency the board holds as Done or archived struck from `waiting_on`: the snapshot holds no
    Done task past its hot day or retired, so one `finished` query settles every dependency it leaves. A server that
    refuses it, as one release behind does, leaves every dependency waiting and is named on stderr."""
    unmet = sorted({dependency for view in views for dependency in view["waiting_on"]})
    if not unmet:
        return views
    try:
        finished = set(agent_wire.graphql(base, _FINISHED, {"ids": unmet}).get("finished") or [])
    except agent_wire.CliError as refused:
        print(f"starpulse: dependencies left unsettled: {refused}", file=sys.stderr)
        return views
    return [
        {**view, "waiting_on": [dependency for dependency in view["waiting_on"] if dependency not in finished]}
        for view in views
    ]


def _show_cold(base: str, task_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """A closed task, whole: a done task past its hot day or one off the snapshot, Done or archived, whose record is
    read from the board; a task the board has no record of is not on it."""
    status, document = agent_wire.get(base, f"/api/task/{urllib.parse.quote(task_id, safe='')}")
    if status == 404:
        raise agent_wire.CliError("not_found", f"{task_id} is not on the board")
    if status != 200:
        raise agent_wire.CliError("unavailable", f"{base} answered {status} for the record of {task_id}")
    record = document["record"]
    lane = lane_id(record["status"])
    done = roles_of(snapshot).done
    # settled rows read archived whatever their file says: a Done file is Done, only another status is truly archived
    state = lane if lane == done or not document.get("archived") else ARCHIVED
    agent = cold_agent(record["id"], record, state, document.get("entered"))
    (view,) = _without_done_dependencies(base, [task_view(agent, snapshot)])
    described = _described(_keyed(view, document), agent["description"], base)
    return {
        **described,
        "final_summary": linkify(record.get("finalSummary", ""), base, view["prs"]),
        "members": record.get("members") or {},
    }


def moves(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    shown = show(args, environ)
    return {"task": shown["key"], "lane": shown["lane"], "moves": shown["moves"]}


def writer(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, str]:
    """Who a task write names as its writer: the agent, with the session and harness `--session` and `--harness` give,
    else `STARPULSE_SESSION` and `STARPULSE_HARNESS`; one neither gives is left out, and the server records it anonymous."""
    named = {
        "session": args.session or environ.get("STARPULSE_SESSION", ""),
        "harness": args.harness or environ.get("STARPULSE_HARNESS", ""),
    }
    return {"actor": AGENT, **{key: value for key, value in named.items() if value}}


def move(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Move the task, or each of several tasks one write at a time, as the agent: the server's verdict, or an error when
    no board writer can answer. A batch answers the tasks moved, or a refusal naming each refused task with its reason."""
    base = agent_wire.server_url(args.server, environ)
    if len(args.task) > 1:
        return _move_each(args, environ, base)
    task = args.task[0]
    status, reply = _move_write(args, environ, base, task)
    message = reply.get("error") or f"{base} answered {status} for /api/tasks/{task}"
    if status == 200:
        return {"ok": True, "task": task, "to": args.to, "reason": "", "skill": "", "advice": reply.get("advice", "")}
    if status == 409:
        return {"ok": False, "task": task, "to": args.to, "reason": message, "skill": reply.get("skill", ""), "advice": ""}
    if status == 404:
        raise agent_wire.CliError("not_found", message)
    if status in (400, 403):
        raise agent_wire.CliError("refused", message)
    raise agent_wire.CliError("unavailable", f"{base}: {message}")


def _move_write(args: argparse.Namespace, environ: Mapping[str, str], base: str, task: str) -> tuple[int, dict[str, Any]]:
    """Write `task` into the column `args.to` as `PUT /api/tasks/{id}` says, over the status it has now."""
    current = _read_record(argparse.Namespace(server=args.server, task=task), environ)
    changes = {"status": args.to.replace("_", " ").title()}
    return agent_wire.put(base, f"/api/tasks/{task}", {"base": {"status": current["status"]}, "changes": changes, **writer(args, environ)})


def _move_each(args: argparse.Namespace, environ: Mapping[str, str], base: str) -> dict[str, Any]:
    """Move each of `args.task` to `args.to`: the tasks moved, or a refusal naming each refused task."""
    moved, refused = [], {}
    for task in args.task:
        try:
            status, reply = _move_write(args, environ, base, task)
        except agent_wire.CliError as error:
            refused[task] = str(error)
            continue
        if status == 200:
            moved.append(task)
        else:
            refused[task] = reply.get("error") or f"{base} answered {status} for /api/tasks/{task}"
    if refused:
        message = f"{len(refused)} of {len(args.task)} tasks refused: {', '.join(refused)}"
        raise agent_wire.CliError("refused", message, moved=moved, refused=refused)
    return {"moved": moved}


def _lifecycle(
    args: argparse.Namespace, environ: Mapping[str, str], path: str, body: dict[str, Any], *, put: bool = False
) -> dict[str, Any]:
    """Send the lifecycle write `body` to `path` for the task as the agent: the server's answer, with a refusal as
    `ok: false` and its reason and skill, or an error when no board writer can answer."""
    base = agent_wire.server_url(args.server, environ)
    status, reply = (agent_wire.put if put else agent_wire.post)(base, path, {**body, **writer(args, environ)})
    message = reply.get("error") or f"{base} answered {status} for {path}"
    if status == 200:
        return {
            "ok": True,
            "task": args.task,
            "to": reply.get("to", ""),
            "reason": "",
            "skill": "",
        }
    if status == 409:
        return {
            "ok": False,
            "task": args.task,
            "to": "",
            "reason": message,
            "skill": reply.get("skill", ""),
        }
    if status == 404 and any(text in message for text in _TASK_MISSING):
        raise agent_wire.CliError("not_found", message)
    if status in (400, 403):
        raise agent_wire.CliError("refused", message)
    raise agent_wire.CliError("unavailable", f"{base}: {message}")


def _kept(output: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """`output` without the keys a verb does not report."""
    return {key: output[key] for key in keys}


def task_dispatch(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Dispatch the session to the task: the task actor pins it and moves a Ready or Needs attention task to In Progress.
    A refusal is `ok: false` with its reason, a task another session holds or a session holding another task."""
    base, path = agent_wire.server_url(args.server, environ), f"/api/tasks/{args.task}"
    who = writer(args, environ)
    body = {"base": {"assignee": args.replaces or ""}, "changes": {"assignee": who.get("session", "")}, **who}
    status, reply = agent_wire.put(base, path, body)
    message = reply.get("error") or f"{base} answered {status} for {path}"
    if status == 202:
        return {"ok": True, "task": args.task, "session": reply.get("session", ""), "reason": "", "skill": ""}
    if status == 409:
        return {"ok": False, "task": args.task, "session": "", "reason": message, "skill": reply.get("skill", "")}
    if status == 404 and any(text in message for text in _TASK_MISSING):
        raise agent_wire.CliError("not_found", message)
    if status in (400, 403, 501):
        raise agent_wire.CliError("refused", message)
    raise agent_wire.CliError("unavailable", f"{base}: {message}")


def task_park(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Park the task on one reason: `--until-task` (`TASK` or `TASK#K`) and `--until` wait, `--operator` needs attention; the server picks the lane."""
    reasons = {"untilTask": args.until_task, "until": list(args.until), "operator": args.operator}
    body = {
        "park": {key: value for key, value in reasons.items() if value},
        **({"comment": args.comment} if args.comment else {}),
    }
    return _kept(_lifecycle(args, environ, f"/api/tasks/{args.task}", body, put=True), LIFECYCLE_KEYS)


def task_freeze(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Ask the task actor to freeze the task in its lane for `--reason`; it carries the request out and comments."""
    return _kept(_lifecycle(args, environ, f"/api/tasks/{args.task}", {"freeze": args.reason}, put=True), LIFECYCLE_KEYS)


def task_unfreeze(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Ask the task actor to lift the task's freeze: it answers the operator or the freezer, and refuses anyone else."""
    return _kept(_lifecycle(args, environ, f"/api/tasks/{args.task}", {"unfreeze": True}, put=True), LIFECYCLE_KEYS)


def record_call(
    base: str,
    path: str,
    status: int,
    reply: Any,
    *,
    ok: tuple[int, ...] = (200,),
    noun: str = "milestone",
    missing: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The JSON object a milestone, doc or task route answered with, or the `agent_wire.CliError` its status maps to."""
    document = reply if isinstance(reply, dict) else {}
    if status in ok and document:
        return document
    message = document.get("error") or f"{base} answered {status} for {path}: is it a StarPulse server?"
    if status == 404 and "error" in document:
        # The server gives both 404s as text only: a board that keeps no such records, else one that is not open.
        absent = (f"is not an open {noun}", f"is not a {noun}", *missing)
        raise agent_wire.CliError("not_found" if any(text in message for text in absent) else "unavailable", message)
    if status in (400, 403, 409):
        # A 400 names the request model and the schema of the field it refused, so the caller sees a valid value.
        raise agent_wire.CliError("refused", message, **{key: document[key] for key in ("model", "schema") if key in document})
    raise agent_wire.CliError("unavailable", f"{base}: {message}")


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text()


def _brief(source: str | None, description: str | None) -> Any:
    if description is not None:
        raise agent_wire.CliError("usage", "task create takes --brief FILE (a JSON object), not --description")
    if source is None:
        return None
    try:
        return json.loads(_read(source))
    except (OSError, ValueError) as error:
        raise agent_wire.CliError("usage", f"--brief {source} is not a JSON object: {error}") from error


def _created_task(args: argparse.Namespace) -> dict[str, Any]:
    """The title and details a `create` command line names, each field only when given."""
    given = {
        "brief": _brief(args.brief, args.description),
        "duplicateQueries": args.duplicate_queries,
        "duplicateResolution": args.duplicate_resolution,
        "priority": args.priority,
        "impact": args.impact,
        "urgency": args.urgency,
        "tier": args.tier,
        "milestone": args.milestone,
        "source": args.source,
        "follows": args.follows,
        "profile": args.profile,
        "labels": args.label,
        "dependencies": args.dependency,
        "blocks": args.blocks,
        "acceptanceCriteria": args.ac,
        "status": args.status,
        "type": args.type,
        "references": args.reference,
        "documentation": args.documentation,
        "definitionOfDone": args.dod,
    }
    return {"title": args.title, **{k: v for k, v in given.items() if v is not None}}


_BY_SOURCE = "query TasksBySource($source: String) { tasks(source: $source) { items { id title lane } } }"


def _open_with_source(args: argparse.Namespace, environ: Mapping[str, str], source: str) -> list[dict[str, Any]]:
    base = agent_wire.server_url(args.server, environ)
    return agent_wire.graphql(base, _BY_SOURCE, {"source": source})["tasks"]["items"]


def task_find(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The open tasks filed under `--source`, each with its id, title and state; none is no error."""
    found = _open_with_source(args, environ, args.source)
    return {"source": args.source, "tasks": [{"id": a["id"], "title": a["title"], "state": a["lane"]} for a in found]}


def task_create(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Create the task the command line names, or each spec of the JSON list in `--batch` in one write: the new key, or
    the keys created as a list under `task`, or a refusal naming them and each refused spec's position and reason when any was refused.
    A `--source` an open task already holds returns that task under `task`, with `existing` true, and writes nothing.
    A created task that a `--blocks` task does not depend on is a refusal carrying the created `task` and, by new task,
    the `unblocked` tasks and why."""
    base, path = agent_wire.server_url(args.server, environ), "/api/tasks"
    if args.batch:
        return _create_batch(args, environ, base, path)
    if args.title is None:
        raise agent_wire.CliError("usage", "name the task's title, or --batch FILE for several")
    if args.source and (held := _open_with_source(args, environ, args.source)):
        return {"task": held[0]["id"], "existing": True}
    status, reply = agent_wire.put_keyed(base, path, {**_created_task(args), **writer(args, environ)}, args.request_key)
    created = record_call(base, path, status, reply, ok=(201,))
    if unblocked := created.get("unblocked"):
        unblocked = {created["task"]: unblocked}
        raise agent_wire.CliError("refused", _not_blocking(unblocked), task=created["task"], unblocked=unblocked)
    return {"task": created["task"]}


def _not_blocking(unblocked: dict[str, dict[str, str]]) -> str:
    return "; ".join(
        f"{task} was created but {name} does not depend on it: {why}"
        for task, names in unblocked.items()
        for name, why in names.items()
    )


def _create_batch(args: argparse.Namespace, environ: Mapping[str, str], base: str, path: str) -> dict[str, Any]:
    """The batch create of the JSON list `args.batch` names (`-` for stdin) for `task_create`."""
    text = _read(args.batch)
    specs = json.loads(text)
    status, reply = agent_wire.put_keyed(base, path, {"tasks": specs, **writer(args, environ)}, args.request_key)
    results = record_call(base, path, status, reply)["results"]
    created = [result["task"] for result in results if "task" in result]
    unblocked = {result["task"]: result["unblocked"] for result in results if result.get("unblocked")}
    refused = {str(position): result["error"] for position, result in enumerate(results, 1) if "error" in result}
    extra = {"unblocked": unblocked} if unblocked else {}
    if refused:
        message = f"{len(refused)} of {len(specs)} tasks refused: " + "; ".join(
            f"#{position} {error}" for position, error in refused.items()
        )
        message += f"; {_not_blocking(unblocked)}" if unblocked else ""
        searched = {str(at): found for at, result in enumerate(results, 1) if (found := result.get("duplicateSearch"))}
        raise agent_wire.CliError(
            "refused",
            message,
            created=created,
            refused=refused,
            **extra,
            **({"duplicateSearch": searched} if searched else {}),
        )
    if unblocked:
        raise agent_wire.CliError("refused", _not_blocking(unblocked), task=created, **extra)
    checked = [result for result in results if "open" in result]
    return {"task": created, **({"checked": checked[0]} if checked else {})}


def _task_edit_call(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    changes: dict[str, Any],
    base_record: dict[str, Any] | None,
    comment: str = "",
    *,
    break_glass: bool = False,
) -> list[str]:
    """Send `changes` to `PUT /api/tasks/{id}` as one write and return the fields that changed; `break_glass` makes it the operator's.

    `base_record` is what the caller read the task as; without one the task is read now, so the edit is refused only
    for a field another writer changes between that read and this write.
    """
    base = agent_wire.server_url(args.server, environ)
    if base_record is None:
        current = _read_record(args, environ)
        base_record = {field: current.get(field) for field in changes.keys() - _UNBASED}
    who = {"actor": OPERATOR, "breakGlass": True} if break_glass else writer(args, environ)
    body = {"base": base_record, "changes": changes, "comment": comment, **who}
    path = f"/api/tasks/{args.task}"
    status, reply = agent_wire.put_keyed(base, path, body)
    return record_call(base, path, status, reply, missing=_TASK_MISSING)["changed"]


def _read_document(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The board's reply for the task `args.task`: its `record`, and whether it is `archived`."""
    base, path = agent_wire.server_url(args.server, environ), f"/api/task/{urllib.parse.quote(args.task, safe='')}"
    status, reply = agent_wire.get(base, path)
    return record_call(base, path, status, reply, missing=_TASK_MISSING)


def _read_record(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The task `args.task` as the board's reader gives it."""
    return _read_document(args, environ)["record"]


def _checklist_flags(args: argparse.Namespace, key: str) -> tuple[list[Any], ...]:
    """The values given to a checklist's add, reword, remove, check and uncheck flags, each `[]` when not given."""
    return tuple(getattr(args, dest.format(key)) or [] for dest in _CHECKLIST_DESTS)


def _checklist_after(args: argparse.Namespace, field: str, items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The checklist `field` after the flags given, or None when it has none.

    A flag names an item by the number the task shows before this edit. A removal sends the whole list without numbers, so
    the board writes it numbered from 1; any other edit sends the numbers, which the board keeps.
    """
    key, name = _CHECKLISTS[field]
    add, reword, remove, check, uncheck = _checklist_flags(args, key)
    if not (add or reword or remove or check or uncheck):
        return None
    reworded = {}
    for value in reword:
        number, colon, wording = value.partition(":")
        if not (colon and number.strip().isdigit()):
            raise agent_wire.CliError("usage", f"--reword-{key} takes N:TEXT, as 2:The new wording")
        reworded[int(number)] = wording
    present = {item["n"] for item in items}
    if absent := [number for number in (*reworded, *remove, *check, *uncheck) if number not in present]:
        raise agent_wire.CliError("refused", f"{args.task} has no {name} item #{absent[0]}")
    kept = [
        {
            "n": item["n"],
            "text": reworded.get(item["n"], item["text"]),
            "checked": (item["checked"] or item["n"] in check) and item["n"] not in uncheck,
        }
        for item in items
        if item["n"] not in remove
    ]
    after = [*kept, *({"text": text, "checked": False} for text in add)]
    return [{k: v for k, v in item.items() if k != "n"} for item in after] if remove else after


def _edited(text: str, environ: Mapping[str, str]) -> str:
    """`text` as the operator leaves it in `$VISUAL`, else `$EDITOR`, else `vi`."""
    editor = shlex.split(environ.get("VISUAL") or environ.get("EDITOR") or "vi")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder, "task.md")
        path.write_text(text)
        if subprocess.run([*editor, str(path)], env={**os.environ, **environ}, check=False).returncode:
            raise agent_wire.CliError("refused", "the editor exited with an error; nothing was imported")
        return path.read_text()


def _edit_in_editor(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The break-glass edit (D5): open the task's rendering, import what the operator changed as Events by the operator."""

    record = _read_record(args, environ)
    try:
        changes = imported(_edited(render_markdown(record), environ), record)
    except MarkdownRefusedError as exc:
        raise agent_wire.CliError("refused", f"{args.task}: {exc}") from exc
    if not changes:
        return {"task": args.task, "changed": []}
    base_record = {field: record.get(field) for field in changes}
    return {
        "task": args.task,
        "changed": _task_edit_call(args, environ, changes, base_record, args.comment, break_glass=True),
    }


def task_edit(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    if args.editor:
        return _edit_in_editor(args, environ)
    changes = {
        field: getattr(args, flag) for flag, field in _TASK_EDIT_FIELDS.items() if getattr(args, flag) is not None
    }
    if args.append_notes:
        changes["appendNotes"] = "\n".join(args.append_notes)
    if args.reason is not None:
        if args.plan is None:
            raise agent_wire.CliError("usage", "--reason says why --plan rewrites the plan; give --plan too")
        changes["planReason"] = args.reason
    checklists = [field for field, (key, _) in _CHECKLISTS.items() if any(_checklist_flags(args, key))]
    if not (changes or checklists or (args.comment or "").strip()):
        flags = (
            *(f"--{flag.replace('_', '-')}" for flag in _TASK_EDIT_FIELDS),
            "--append-notes",
            *(
                f"--{dest.format(key).replace('_', '-')}"
                for key, _ in _CHECKLISTS.values()
                for dest in _CHECKLIST_DESTS
            ),
        )
        raise agent_wire.CliError("usage", f"name what to change: {', '.join(flags)}")
    base_record = None
    if args.base is not None:
        try:
            base_record = json.loads(args.base)
        except ValueError:
            base_record = None
        if not isinstance(base_record, dict):
            raise agent_wire.CliError("usage", '--base must be a JSON object of the values read, as {"title": "..."}')
    unbased = base_record is not None and not changes.keys() - _UNBASED <= base_record.keys()
    if checklists or unbased:
        # The items are edited as read, so the same read is the edit's base, as it is for a field `--base` leaves out.
        record = _read_record(args, environ)
        for field in checklists:
            changes[field] = _checklist_after(args, field, record[field])
        read = {field: record.get(field) for field in changes.keys() - _UNBASED}
        base_record = {**read, **(base_record or {})}
    return {"task": args.task, "changed": _task_edit_call(args, environ, changes, base_record, args.comment)}


def task_assign(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changed = _task_edit_call(args, environ, {"profile": args.profile}, None)
    return {"task": args.task, "profile": args.profile, "changed": changed}


def task_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Archive one task, or several, one `DELETE` each: the keys archived, or a refusal naming them and each refused
    key's reason when any key was refused."""
    base, body = agent_wire.server_url(args.server, environ), {"reason": args.reason, **writer(args, environ)}
    if len(args.task) == 1:
        path = f"/api/tasks/{args.task[0]}"
        status, reply = agent_wire.delete(base, path, body)
        answer = record_call(base, path, status, reply, missing=_TASK_MISSING)
        key = args.task[0]
        return {"archived": [] if answer["requested"] else [key], "requested": [key] if answer["requested"] else []}
    archived, requested, refused = [], [], {}
    for task in args.task:
        path = f"/api/tasks/{task}"
        status, reply = agent_wire.delete(base, path, body)
        try:
            answer = record_call(base, path, status, reply, missing=_TASK_MISSING)
            (requested if answer["requested"] else archived).append(task)
        except agent_wire.CliError as error:
            refused[task] = str(error)
    if refused:
        message = f"{len(refused)} of {len(args.task)} tasks refused: {', '.join(refused)}"
        raise agent_wire.CliError("refused", message, archived=archived, requested=requested, refused=refused)
    return {"archived": archived, "requested": requested}


def task_restore(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), f"/api/tasks/{args.task}"
    status, reply = agent_wire.put(base, path, {"archived": False, **writer(args, environ)})
    return {"task": record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_reopen(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), f"/api/tasks/{args.task}"
    status, reply = agent_wire.put(base, path, {"reopen": args.reason, **writer(args, environ)})
    return {"task": record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_retire(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), f"/api/tasks/{args.task}"
    status, reply = agent_wire.put(base, path, {"retired": True})
    return {"task": record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


#: The most retired tasks one page of `starpulse task retired` takes: the server's own most.
_RETIRED_PAGE = 500


def task_retired(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base = agent_wire.server_url(args.server, environ)
    asked = (("task", args.task), ("milestone", args.milestone), ("fields", "dependencies" if args.ids else ""))
    filters = {key: value for key, value in asked if value}
    tasks: list[Any] = []
    params = filters or {"limit": _RETIRED_PAGE}  # every retired task is read a page at a time, newest retired first
    while True:
        path = f"/api/retired?{urllib.parse.urlencode(params)}"
        status, reply = agent_wire.get(base, path)
        answered = record_call(base, path, status, reply, noun="retired task")
        tasks += answered["tasks"]
        if filters or not answered.get("next"):
            return {"tasks": tasks}
        params = {"limit": _RETIRED_PAGE, "before": answered["next"]}


def task_cold_done(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return {"tasks": list(_cold_done(agent_wire.server_url(args.server, environ), None))}


def task_complete(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), f"/api/tasks/{args.task}"
    status, reply = agent_wire.put(base, path, {"completed": True})
    return {"task": record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_checkpoint_ac(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    evidence = args.evidence.strip()
    if not evidence:
        raise agent_wire.CliError("usage", "evidence is required to check an Acceptance Criterion")
    with step_times.timed("checkpoint", agent_wire.server_url(args.server, environ)) as steps:
        with step_times.step(steps, "read"):
            criteria = _read_record(args, environ).get("acceptanceCriteria") or []
        if args.criterion not in {item["n"] for item in criteria}:
            raise agent_wire.CliError("refused", f"{args.task} has no Acceptance Criteria item #{args.criterion}")
        checked = [{**item, "checked": True} if item["n"] == args.criterion else item for item in criteria]
        with step_times.step(steps, "write"):
            changed = _task_edit_call(
                args,
                environ,
                {"acceptanceCriteria": checked},
                {"acceptanceCriteria": criteria},
                f"Verified AC #{args.criterion}: {evidence}",
            )
    return {"task": args.task, "criterion": args.criterion, "changed": changed}


_PULL = (
    "query($repo: String!, $number: Int!) { pull(repo: $repo, number: $number) { repo number state isDraft mergeable "
    "baseRefName headRefName headRefOid body checks requiredChecks { name result } threads unresolvedThreads { id author } updatedAt mergedAt mergeSha "
    "fetchedAt files } }"
)


def pull_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The stored record of one pull request, with the paths it changes, from the server's PR store: no GitHub read."""
    cited = cited_pull(args.pull)
    if not cited:
        raise agent_wire.CliError("usage", f"{args.pull!r} is no pull request: write `owner/name#N` or its GitHub URL")
    base = agent_wire.server_url(args.server, environ)
    found = agent_wire.graphql(base, _PULL, {"repo": cited.repo, "number": cited.number})["pull"]
    if not found:
        raise agent_wire.CliError("not_found", f"the store holds no pull request {cited.repo}#{cited.number}")
    return found


def _quoted(collection: str, ident: str) -> str:
    return f"{collection}/{urllib.parse.quote(ident, safe='')}"


def _revision(base: str, path: str, key: str) -> str:
    """The `revision` of the record at `path`, which a PUT names as its `base`."""
    status, reply = agent_wire.get(base, path)
    return record_call(base, path, status, reply, noun=key)[key]["revision"]


def milestone_list(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/milestones"
    status, reply = agent_wire.post(base, path, {})
    return {"milestones": record_call(base, path, status, reply)["milestones"]}


def milestone_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/milestones", args.milestone)
    status, reply = agent_wire.get(base, path)
    return record_call(base, path, status, reply)["milestone"]


def milestone_add(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/milestones"
    body: dict[str, Any] = {"title": args.title}
    body.update(_milestone_fields(args))
    status, reply = agent_wire.put(base, path, body)
    return {"milestone": record_call(base, path, status, reply, ok=(201,))["milestone"]}


def milestone_edit(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/milestones", args.milestone)
    changes = {**({"title": args.title} if args.title is not None else {}), **_milestone_fields(args)}
    if not changes:
        raise agent_wire.CliError("usage", "name what to change: --title, --outcome, --spec, --adr or --retro")
    status, reply = agent_wire.put(base, path, {"base": _revision(base, path, "milestone"), **changes})
    document = record_call(base, path, status, reply)
    return {"milestone": document["milestone"], "changed": document["changed"]}


def milestone_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/milestones", args.milestone)
    status, reply = agent_wire.delete(base, path)
    return {"milestone": record_call(base, path, status, reply)["milestone"]}


def doc_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/docs", args.doc)
    status, reply = agent_wire.get(base, path)
    return record_call(base, path, status, reply, noun="doc")["doc"]


def _doc_fields(args: argparse.Namespace) -> dict[str, Any]:
    """The detail fields (type, body) the caller gave."""
    return {field: value for field, value in {"type": args.type, "body": args.body}.items() if value is not None}


def doc_create(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/docs"
    body = {"title": args.title, **_doc_fields(args), **({"folder": args.folder} if args.folder is not None else {})}
    status, reply = agent_wire.put(base, path, body)
    doc = record_call(base, path, status, reply, ok=(201,), noun="doc")["doc"]
    if args.task is None:
        return {"doc": doc}
    linked = _read_record(args, environ)["documentation"]  # the server reads the id as the doc's file
    changed = _task_edit_call(args, environ, {"documentation": [*linked, doc]}, {"documentation": linked})
    return {"doc": doc, "task": args.task, "changed": changed}


def doc_update(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/docs", args.doc)
    changes = {**({"title": args.title} if args.title is not None else {}), **_doc_fields(args)}
    if not changes:
        raise agent_wire.CliError("usage", "name what to change: --title, --type or --body")
    status, reply = agent_wire.put(base, path, {"base": _revision(base, path, "doc"), **changes})
    document = record_call(base, path, status, reply, noun="doc")
    return {"doc": document["doc"], "changed": document["changed"]}


def doc_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/docs", args.doc)
    status, reply = agent_wire.delete(base, path)
    return {"doc": record_call(base, path, status, reply, noun="doc")["doc"]}


def doc_restore(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), _quoted("/api/docs", args.doc)
    sent = {"base": _revision(base, path, "doc"), "archived": False, **({"folder": args.folder} if args.folder else {})}
    status, reply = agent_wire.put(base, path, sent)
    return {"doc": record_call(base, path, status, reply, noun="doc")["doc"]}


def search(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base = agent_wire.server_url(args.server, environ)
    given = {
        "limit": args.limit,
        "label": args.label,
        "finished_within_days": args.finished_within_days,
        "before": args.before,
    }
    query = {"q": " ".join(args.query), **{key: value for key, value in given.items() if value is not None}}
    path = f"/api/search{'/similar' if args.similar else ''}?{urllib.parse.urlencode(query, doseq=True)}"
    status, reply = agent_wire.get(base, path)
    found = record_call(base, path, status, reply, noun="search")
    return {"query": found["query"], "hits": found["hits"]}


def _milestone_fields(args: argparse.Namespace) -> dict[str, Any]:
    """The detail fields (outcome, specs, ADRs, retro) the caller gave; a list flag given at all replaces the list."""
    given = {"outcome": args.outcome, "specs": args.spec, "adrs": args.adr, "retro": args.retro}
    return {field: value for field, value in given.items() if value is not None}


def with_activity(view: dict[str, Any], working: str, harness: SessionHarness, now: float) -> dict[str, Any]:
    """`view` with the `session_activity` of the session holding it, when it sits in the `working` lane the machine
    declares and has a holder: working, idle since its last agent turn, or `unknown` when the holder is no running
    session with a transcript."""
    if view["lane"] != working or not view["assignee"]:
        return view
    return {**view, "session_activity": harness.activity(view["assignee"], now)}


def _active(view: dict[str, Any], snapshot: Mapping[str, Any], harness: SessionHarness) -> dict[str, Any]:
    return with_activity(view, roles_of(snapshot).working, harness, time.time())
