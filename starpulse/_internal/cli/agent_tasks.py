"""The board, task, milestone, doc and search verbs of `starpulse ... --agent`: reads and writes of the board's records."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from starpulse._internal.board.view import AGENT, board_columns, board_flow, cold_agent, done_ids, task_view
from starpulse._internal.cli import agent_wire
from starpulse._internal.cli.agent_keys import CLAIM_KEYS, LIFECYCLE_KEYS

#: What a task route's 404 says when the board has no such task, as opposed to a board that cannot read or write tasks.
_TASK_MISSING = ("is not on the board", "has no record to read")

#: Each `task edit` flag's destination and the record field it sets, in the order `changed` reports them.
_TASK_EDIT_FIELDS = {
    "title": "title",
    "type": "type",
    "priority": "priority",
    "milestone": "milestone",
    "label": "labels",
    "dependency": "dependencies",
    "reference": "references",
    "documentation": "documentation",
    "modified_file": "modifiedFiles",
    "description": "description",
    "plan": "plan",
    "notes": "notes",
    "final_summary": "finalSummary",
}
#: The checklists `task edit` changes: each record field's flag key (`--ac`, `--reword-ac`, ...) and the name a refusal gives it.
_CHECKLISTS = {"acceptanceCriteria": ("ac", "Acceptance Criteria"), "definitionOfDone": ("dod", "Definition of Done")}
#: A checklist's flag destinations, as `{}` stands for its key: add, reword, remove, check and uncheck.
_CHECKLIST_DESTS = ("{}", "reword_{}", "remove_{}", "check_{}", "uncheck_{}")


def board(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = agent_wire.snapshot(args, environ)
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
            and (not session or agent.get("assignee", "") == session)
        )

    board = board_columns(snapshot, kept, args.state)
    if args.milestone and snapshot.get("cold_done") and args.state in (None, "done"):
        done = done_ids(snapshot)
        column = next(column for column in board["columns"] if column["state"] == "done")
        bare = {"milestone": "", "labels": [], "dependencies": [], "prs": [], "moves": {}}
        cards = [bare | card for card in _cold_done(agent_wire.server_url(args.server, environ))]
        column["tasks"] += [task_view(card, snapshot, done) for card in cards if kept(card)]
    return board


def _cold_done(base: str) -> Iterator[dict[str, Any]]:
    """Every done task past its hot day as a board card, newest first; the snapshot lists them by id only."""
    before = ""
    while True:
        status, page = agent_wire.get(base, f"/api/done?limit=100{before}")
        if status != 200:
            raise agent_wire.CliError(
                "unavailable", f"{base} answered {status} for /api/done: cannot list the done tasks"
            )
        yield from page["tasks"]
        if not page["more"]:
            return
        before = f"&before={page['tasks'][-1]['entered']}"


def show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = agent_wire.snapshot(args, environ)
    wanted = args.task.casefold()
    agents = {agent["id"].casefold(): agent for agent in board_flow(snapshot)["agents"]}
    if (agent := agents.get(wanted)) is None:
        cold = next((task for task in snapshot.get("cold_done", ()) if task.casefold() == wanted), None)
        if cold is not None:
            return _show_cold(agent_wire.server_url(args.server, environ), cold, snapshot)
        settled_id, settled = next(
            ((key, value) for key, value in snapshot["settled"].items() if key.casefold() == wanted), (None, None)
        )
        if settled is None:
            raise agent_wire.CliError("not_found", f"{args.task} is not on the board")
        # A settled task has left the lanes, and the snapshot keeps only where it settled.
        agent = {
            "id": settled_id,
            "title": "",
            "state": settled["state"],
            "model": "",
            "milestone": "",
            "labels": [],
            "dependencies": [],
            "prs": [],
            "moves": {},
            "description": "",
        }
    return {**task_view(agent, snapshot), "description": agent["description"]}


def _show_cold(base: str, task_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """A done task past its hot day, whole: the snapshot holds only its id, so its record is read from the board."""
    status, document = agent_wire.get(base, f"/api/task/{urllib.parse.quote(task_id, safe='')}")
    if status != 200:
        raise agent_wire.CliError("unavailable", f"{base} answered {status} for the record of {task_id}")
    agent = cold_agent(task_id, document["record"])
    return {**task_view(agent, snapshot), "description": agent["description"]}


def moves(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    shown = show(args, environ)
    return {"task": shown["id"], "lane": shown["lane"], "moves": shown["moves"]}


def writer_flags(sub: argparse.ArgumentParser) -> None:
    """Add the flags that name the session and harness a task write is made from."""
    sub.add_argument(
        "--session",
        default="",
        help="the session writing, recorded as the assignee of a claimed task and on the change (else `STARPULSE_SESSION`)",
    )
    sub.add_argument(
        "--harness", default="", help="the harness of that session (`claude`, `cursor`), else `STARPULSE_HARNESS`"
    )


def _writer(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, str]:
    """Who a task write names as its writer: the agent, with the session and harness `--session` and `--harness` give,
    else `STARPULSE_SESSION` and `STARPULSE_HARNESS`; one neither gives is left out, and the server records it anonymous."""
    named = {
        "session": args.session or environ.get("STARPULSE_SESSION", ""),
        "harness": args.harness or environ.get("STARPULSE_HARNESS", ""),
    }
    return {"actor": AGENT, **{key: value for key, value in named.items() if value}}


def move(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Move the task as the agent: the server's verdict, or an error when no board writer can answer."""
    base = agent_wire.server_url(args.server, environ)
    body = {"task": args.task, "to": args.to, **_writer(args, environ)}
    status, reply = agent_wire.post(base, "/api/move", body)
    message = reply.get("error") or f"{base} answered {status} for /api/move"
    if status == 200:
        return {
            "ok": True,
            "task": args.task,
            "to": args.to,
            "reason": "",
            "skill": "",
            "advice": reply.get("advice", ""),
        }
    if status == 409:
        return {
            "ok": False,
            "task": args.task,
            "to": args.to,
            "reason": message,
            "skill": reply.get("skill", ""),
            "advice": "",
        }
    if status == 404:
        raise agent_wire.CliError("not_found", message)
    if status in (400, 403):
        raise agent_wire.CliError("refused", message)
    raise agent_wire.CliError("unavailable", f"{base}: {message}")


def _lifecycle(
    args: argparse.Namespace, environ: Mapping[str, str], verb: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Post the lifecycle verb `verb` (`claim`, `park`, `review`) for the task as the agent: the server's answer, with a
    refusal as `ok: false` and its reason and skill, or an error when no board writer can answer."""
    base, path = agent_wire.server_url(args.server, environ), f"/api/{verb}"
    status, reply = agent_wire.post(base, path, {"task": args.task, **fields, **_writer(args, environ)})
    message = reply.get("error") or f"{base} answered {status} for {path}"
    if status == 200:
        return {
            "ok": True,
            "task": args.task,
            "to": reply.get("to", ""),
            "assignee": reply.get("assignee", ""),
            "reason": "",
            "skill": "",
        }
    if status == 409:
        return {
            "ok": False,
            "task": args.task,
            "to": "",
            "assignee": "",
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


def task_claim(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Claim the task for the session: it moves to In Progress with that session as assignee, refused when another holds it."""
    return _kept(_lifecycle(args, environ, "claim", {}), CLAIM_KEYS)


def _criterion(text: str) -> dict[str, Any]:
    """The `--until` criterion `text` (YAML or JSON) names, refused when it is not a mapping."""
    try:
        criterion = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise agent_wire.CliError("refused", f"--until is not YAML or JSON: {exc}") from exc
    if not isinstance(criterion, dict):
        raise agent_wire.CliError("refused", f"--until must be a mapping, got {text!r}")
    return criterion


def task_park(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Park the task on one reason: `--until-task` and `--until` wait, `--operator` needs attention; the server picks the lane."""
    fields = {
        "untilTask": args.until_task,
        "until": [_criterion(text) for text in args.until],
        "operator": args.operator,
        "comment": args.comment,
    }
    given = {key: value for key, value in fields.items() if value}
    return _kept(_lifecycle(args, environ, "park", given), LIFECYCLE_KEYS)


def task_review(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Move the task to Review with `--ref` references and `--summary`: the configured rules judge the resulting record."""
    fields = {"references": args.ref, "summary": args.summary, "comment": args.comment}
    given = {key: value for key, value in fields.items() if value}
    return _kept(_lifecycle(args, environ, "review", given), LIFECYCLE_KEYS)


def _record_call(
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
        absent = (f"is not an open {noun}", *missing)
        raise agent_wire.CliError("not_found" if any(text in message for text in absent) else "unavailable", message)
    if status in (400, 403, 409):
        raise agent_wire.CliError("refused", message)
    raise agent_wire.CliError("unavailable", f"{base}: {message}")


def create_flags(sub: argparse.ArgumentParser) -> None:
    """Add the detail flags of a task a `create` or `miss` command files; the title is the caller's."""
    sub.add_argument("--description", help="the task's Description section")
    sub.add_argument("--priority", help="`high`, `medium` or `low`")
    sub.add_argument("--milestone", help="the milestone's id (`m-106`)")
    sub.add_argument("--profile", "--assignee", dest="profile", help="the agent profile it is routed to (`@agent-standard-high`)")
    sub.add_argument("--label", action="append", help="a label; repeat for several")
    sub.add_argument("--dependency", action="append", help="a task it depends on; repeat for several")
    sub.add_argument("--ac", action="append", help="an Acceptance Criterion; repeat for several, in order")
    sub.add_argument("--status", help="the lane to open it in, else the board's first (`Waiting`)")
    sub.add_argument("--type", help="the task's type (`bug`)")
    sub.add_argument("--reference", action="append", help="a reference; repeat for several")
    sub.add_argument(
        "--documentation",
        action="append",
        help="a documentation link, or an open doc's id (`doc-12`) for its file; repeat for several",
    )
    sub.add_argument("--dod", action="append", help="a Definition of Done item; repeat for several, in order")


def _created_task(args: argparse.Namespace) -> dict[str, Any]:
    """The title and details a `create` or `miss` command line names, each field only when given."""
    given = {
        "description": args.description,
        "priority": args.priority,
        "milestone": args.milestone,
        "profile": args.profile,
        "labels": args.label,
        "dependencies": args.dependency,
        "acceptanceCriteria": args.ac,
        "status": args.status,
        "type": args.type,
        "references": args.reference,
        "documentation": args.documentation,
        "definitionOfDone": args.dod,
    }
    return {"title": args.title, **{k: v for k, v in given.items() if v is not None}}


def task_create(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/tasks"
    status, reply = agent_wire.post(base, path, {**_created_task(args), **_writer(args, environ)})
    return {"task": _record_call(base, path, status, reply, ok=(201,))["task"]}


def task_verdict(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/verdict"
    body = {"task": args.task, "check": args.check, "verdict": args.verdict, "evidence": args.evidence}
    if args.fix:
        body["fix"] = args.fix
    status, reply = agent_wire.post(base, path, {**body, **_writer(args, environ)})
    judged = _record_call(base, path, status, reply, missing=_TASK_MISSING)
    return {key: judged[key] for key in ("task", "check", "verdict")}


def task_miss(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/miss"
    body = {"task": args.task, "check": args.check, "fix": _created_task(args), "evidence": args.evidence}
    status, reply = agent_wire.post(base, path, {**body, **_writer(args, environ)})
    return _record_call(base, path, status, reply, missing=_TASK_MISSING)


def _task_edit_call(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    changes: dict[str, Any],
    base_record: dict[str, Any] | None,
    comment: str = "",
) -> list[str]:
    """Send `changes` to `/api/edit` as one write and return the fields that changed.

    `base_record` is what the caller read the task as; without one the task is read now, so the edit is refused only
    for a field another writer changes between that read and this write.
    """
    base = agent_wire.server_url(args.server, environ)
    if base_record is None:
        current = _read_record(args, environ)
        base_record = {field: current.get(field) for field in changes}
    body = {"task": args.task, "base": base_record, "changes": changes, "comment": comment, **_writer(args, environ)}
    status, reply = agent_wire.post(base, "/api/edit", body)
    return _record_call(base, "/api/edit", status, reply, missing=_TASK_MISSING)["changed"]


def _read_record(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The task `args.task` as the board's reader gives it."""
    base, path = agent_wire.server_url(args.server, environ), f"/api/task/{urllib.parse.quote(args.task, safe='')}"
    status, reply = agent_wire.get(base, path)
    return _record_call(base, path, status, reply, missing=_TASK_MISSING)["record"]


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


def task_edit(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changes = {
        field: getattr(args, flag) for flag, field in _TASK_EDIT_FIELDS.items() if getattr(args, flag) is not None
    }
    if args.append_notes:
        changes["appendNotes"] = "\n".join(args.append_notes)
    checklists = [field for field, (key, _) in _CHECKLISTS.items() if any(_checklist_flags(args, key))]
    if not changes and not checklists:
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
    if checklists:
        record = _read_record(args, environ)  # the items are edited as read, so the same read is the edit's base
        for field in checklists:
            changes[field] = _checklist_after(args, field, record[field])
        read = {field: record.get(field) for field in changes if field != "appendNotes"}
        base_record = {**read, **(base_record or {})}
    return {"task": args.task, "changed": _task_edit_call(args, environ, changes, base_record, args.comment)}


def task_assign(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changed = _task_edit_call(args, environ, {"profile": args.profile}, None)
    return {"task": args.task, "profile": args.profile, "changed": changed}


def task_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/archive"
    status, reply = agent_wire.post(base, path, {"task": args.task, "reason": args.reason, **_writer(args, environ)})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_restore(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/restore"
    status, reply = agent_wire.post(base, path, {"task": args.task, **_writer(args, environ)})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_retire(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/retire"
    status, reply = agent_wire.post(base, path, {"task": args.task})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_retired(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base = agent_wire.server_url(args.server, environ)
    path = f"/api/retired?task={urllib.parse.quote(args.task, safe='')}" if args.task else "/api/retired"
    status, reply = agent_wire.get(base, path)
    return {"tasks": _record_call(base, path, status, reply, noun="retired task")["tasks"]}


def task_import_retired(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/retired/import"
    files = [Path(file) for file in args.files]
    if unreadable := [str(file) for file in files if not file.is_file()]:
        raise agent_wire.CliError("usage", f"no such file: {', '.join(unreadable)}")
    tasks = []
    for file in files:  # the bytes as kept: read_text would turn a CRLF file's line ends into LF
        status, reply = agent_wire.post(base, path, {"name": file.name, "text": file.read_bytes().decode()})
        tasks.append(_record_call(base, path, status, reply, noun="retired task")["task"])
    return {"tasks": tasks}


def task_complete(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/complete"
    status, reply = agent_wire.post(base, path, {"task": args.task})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def task_checkpoint_ac(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    evidence = args.evidence.strip()
    if not evidence:
        raise agent_wire.CliError("usage", "evidence is required to check an Acceptance Criterion")
    criteria = _read_record(args, environ).get("acceptanceCriteria") or []
    if args.criterion not in {item["n"] for item in criteria}:
        raise agent_wire.CliError("refused", f"{args.task} has no Acceptance Criteria item #{args.criterion}")
    checked = [{**item, "checked": True} if item["n"] == args.criterion else item for item in criteria]
    changed = _task_edit_call(
        args,
        environ,
        {"acceptanceCriteria": checked},
        {"acceptanceCriteria": criteria},
        f"Verified AC #{args.criterion}: {evidence}",
    )
    return {"task": args.task, "criterion": args.criterion, "changed": changed}


def milestone_list(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/milestones"
    status, reply = agent_wire.get(base, path)
    return {"milestones": _record_call(base, path, status, reply)["milestones"]}


def milestone_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = (
        agent_wire.server_url(args.server, environ),
        f"/api/milestones/{urllib.parse.quote(args.milestone, safe='')}",
    )
    status, reply = agent_wire.get(base, path)
    return _record_call(base, path, status, reply)["milestone"]


def milestone_add(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/milestones"
    body: dict[str, Any] = {"title": args.title}
    body.update(_milestone_fields(args))
    status, reply = agent_wire.post(base, path, body)
    return {"milestone": _record_call(base, path, status, reply, ok=(201,))["milestone"]}


def milestone_edit(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/milestones/edit"
    changes = {**({"title": args.title} if args.title is not None else {}), **_milestone_fields(args)}
    if not changes:
        raise agent_wire.CliError("usage", "name what to change: --title, --outcome, --spec, --adr or --retro")
    status, reply = agent_wire.post(base, path, {"milestone": args.milestone, "changes": changes})
    document = _record_call(base, path, status, reply)
    return {"milestone": document["milestone"], "changed": document["changed"]}


def milestone_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/milestones/archive"
    status, reply = agent_wire.post(base, path, {"milestone": args.milestone})
    return {"milestone": _record_call(base, path, status, reply)["milestone"]}


def doc_list(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/docs"
    status, reply = agent_wire.get(base, path)
    return {"docs": _record_call(base, path, status, reply, noun="doc")["docs"]}


def doc_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), f"/api/docs/{urllib.parse.quote(args.doc, safe='')}"
    status, reply = agent_wire.get(base, path)
    return _record_call(base, path, status, reply, noun="doc")["doc"]


def _doc_fields(args: argparse.Namespace) -> dict[str, Any]:
    """The detail fields (type, body) the caller gave."""
    return {field: value for field, value in {"type": args.type, "body": args.body}.items() if value is not None}


def doc_create(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/docs"
    body = {"title": args.title, **_doc_fields(args), **({"folder": args.folder} if args.folder is not None else {})}
    status, reply = agent_wire.post(base, path, body)
    doc = _record_call(base, path, status, reply, ok=(201,), noun="doc")["doc"]
    if args.task is None:
        return {"doc": doc}
    linked = _read_record(args, environ)["documentation"]  # the server reads the id as the doc's file
    changed = _task_edit_call(args, environ, {"documentation": [*linked, doc]}, {"documentation": linked})
    return {"doc": doc, "task": args.task, "changed": changed}


def doc_update(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/docs/edit"
    changes = {**({"title": args.title} if args.title is not None else {}), **_doc_fields(args)}
    if not changes:
        raise agent_wire.CliError("usage", "name what to change: --title, --type or --body")
    status, reply = agent_wire.post(base, path, {"doc": args.doc, "changes": changes})
    document = _record_call(base, path, status, reply, noun="doc")
    return {"doc": document["doc"], "changed": document["changed"]}


def doc_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/docs/archive"
    status, reply = agent_wire.post(base, path, {"doc": args.doc})
    return {"doc": _record_call(base, path, status, reply, noun="doc")["doc"]}


def doc_restore(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = agent_wire.server_url(args.server, environ), "/api/docs/restore"
    status, reply = agent_wire.post(base, path, {"doc": args.doc, **({"folder": args.folder} if args.folder else {})})
    return {"doc": _record_call(base, path, status, reply, noun="doc")["doc"]}


def search(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base = agent_wire.server_url(args.server, environ)
    given = {"limit": args.limit, "label": args.label, "finished_within_days": args.finished_within_days}
    query = {"q": " ".join(args.query), **{key: value for key, value in given.items() if value is not None}}
    path = f"/api/search?{urllib.parse.urlencode(query, doseq=True)}"
    status, reply = agent_wire.get(base, path)
    found = _record_call(base, path, status, reply, noun="search")
    return {"query": found["query"], "hits": found["hits"]}


def _milestone_fields(args: argparse.Namespace) -> dict[str, Any]:
    """The detail fields (outcome, specs, ADRs, retro) the caller gave; a list flag given at all replaces the list."""
    given = {"outcome": args.outcome, "specs": args.spec, "adrs": args.adr, "retro": args.retro}
    return {field: value for field, value in given.items() if value is not None}
