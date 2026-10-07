"""The Jira adapter: a project's workflow in as the Board machine, its issues in as board tasks.

Jira keeps a workflow apart from the issues that run through it. `import_workflow` reads one workflow from the
site's `GET /rest/api/2/workflows/search` and compiles it as the Board machine: a state per status, an event per
transition (an `INITIAL` one marks where an issue starts, a `GLOBAL` one leaves every other status). `JiraProject`
then polls the project's issues (`GET /rest/api/2/search/jql`) and hands each to a feed as a `BoardTask` in the lane
of its status, in the team of its Jira project. A status in the done category settles the task as `completed`.
The adapter only reads: it has no writer, so the page offers the workflow's moves but the site is not changed by them.
It is the `[board] type = "jira"` adapter.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from starpulse.board import Board
from starpulse.contracts.adapters import BoardTask, TaskKeys
from starpulse.domain.machine_definition import MachineDefinitionError, compile_document, validate
from starpulse.domain.snapshot import Qualify, describe
from starpulse.upstream_backlog import board_moves, lane_id

if TYPE_CHECKING:
    from starpulse.board_feed import BoardFeed
    from starpulse.store.event_log import EventLog

logger = logging.getLogger(__name__)

#: A page of issues carries these fields and no others.
_FIELDS = "summary,description,status,project,assignee,labels,created,resolutiondate,issuelinks"
#: Where a status category sits on the Board: columns run from not started to done.
_CATEGORY_ORDER = {"TODO": 0, "IN_PROGRESS": 1, "DONE": 2}
#: The `[board]` settings this adapter reads.
_SETTINGS = {"type", "url", "project", "workflow", "token_env", "user", "interval"}


def jira_keys(project: str) -> TaskKeys:
    """Task keys `<PROJECT>-N` and the branches that name them, in any case."""
    key = rf"{re.escape(project)}-\d+"
    return TaskKeys(
        key=re.compile(key, re.I),
        branch=re.compile(rf"(?:refs/heads/)?(?:[^/]+/)*?({key})(?=$|[-_/])", re.I),
    )


def _event(transition: Mapping[str, Any]) -> str:
    """A transition's name as a machine event: `Start work` is `START_WORK`."""
    name = re.sub(r"[^A-Za-z0-9]+", "_", str(transition.get("name", ""))).strip("_").upper()
    if not name[:1].isalpha():
        raise ValueError(
            f"transition {transition.get('id')!r} is named {transition.get('name')!r}, which makes no event"
        )
    return name


def import_workflow(page: Mapping[str, Any], name: str) -> tuple[dict, frozenset[str]]:
    """The Board machine of the workflow `name` in a `workflows/search` response, drawn, and the lanes that are done.

    The machine is compiled, so what is drawn is what StarPulse runs. A status is a lane (`lane_id` of its name). The
    workflow is refused when it is not in the response, has no single initial transition, makes one lane of two
    statuses, or lists a status that no transition touches.
    """
    workflow = next((w for w in page.get("values", ()) if w.get("name") == name), None)
    if workflow is None:
        raise ValueError(f"jira: the site returned no workflow named {name!r}")
    try:
        return _import(workflow, {s["statusReference"]: s for s in page.get("statuses", ())})
    except (ValueError, MachineDefinitionError, KeyError) as error:
        raise ValueError(f"jira: workflow {name!r}: {error!s}") from error


def _import(workflow: Mapping[str, Any], details: Mapping[str, Mapping[str, Any]]) -> tuple[dict, frozenset[str]]:
    refs = [s["statusReference"] for s in workflow["statuses"]]
    if unknown := [ref for ref in refs if ref not in details]:
        raise ValueError(f"statuses {unknown} are not described by the response")
    refs.sort(key=lambda ref: _CATEGORY_ORDER.get(details[ref].get("statusCategory", ""), 1))
    names = {ref: details[ref]["name"] for ref in refs}
    lanes = {ref: lane_id(names[ref]) for ref in refs}
    if len(set(lanes.values())) != len(refs):
        clashing = sorted(n for n in names.values() if [m for m in names.values() if lane_id(m) == lane_id(n)][1:])
        raise ValueError(f"statuses {clashing} make one lane")

    events: dict[str, list[dict]] = {}
    initial: list[str] = []
    touched: set[str] = set()
    for transition in workflow["transitions"]:
        target = transition["toStatusReference"]
        touched.add(target)
        if transition["type"] == "INITIAL":
            initial.append(target)
            continue
        linked = [link["fromStatusReference"] for link in transition.get("links", ()) if "fromStatusReference" in link]
        touched.update(linked)
        sources = [ref for ref in refs if ref != target] if transition["type"] == "GLOBAL" else linked
        if sources:
            events.setdefault(_event(transition), []).append(
                {"from": [lanes[ref] for ref in sources], "to": lanes[target]}
            )
    if orphans := [names[ref] for ref in refs if ref not in touched]:
        raise ValueError(f"statuses {orphans} are in no transition")
    if len(initial) != 1:
        raise ValueError(f"it needs exactly one initial transition, found {len(initial)}")

    done = frozenset(lanes[ref] for ref in refs if details[ref].get("statusCategory") == "DONE")
    leaving = {source for entries in events.values() for entry in entries for source in entry["from"]}
    document = {
        "name": "JiraBoard",
        "states": {
            lanes[ref]: {
                **({"initial": True} if ref == initial[0] else {}),
                **({"final": True} if lanes[ref] in done and lanes[ref] not in leaving else {}),
            }
            for ref in refs
        },
        "events": events,
    }
    validate(document)
    drawn = describe(compile_document(document, Path(f"jira workflow {workflow['name']}")).machine)
    titles = {lanes[ref]: names[ref] for ref in refs}
    return {
        "states": [{**s, "name": titles[s["id"]], "final": s["id"] in done} for s in drawn["states"]],
        "transitions": drawn["transitions"],
        "mainLine": list(lanes.values()),
    }, done


def _when(value: object) -> float | None:
    """A Jira timestamp (`2026-09-28T09:15:00.000-0700`) as epoch seconds; None when there is none."""
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
    except ValueError:
        return None


Fetch = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


def http_fetch(url: str, authorization: str) -> Fetch:
    """A GET of one JSON resource of the Jira site at `url`, sent with `authorization` when it is not empty."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"jira: {url!r} is not an http or https URL")
    base = url.rstrip("/")
    headers = {"Accept": "application/json", **({"Authorization": authorization} if authorization else {})}

    def fetch(path: str, query: Mapping[str, str]) -> Mapping[str, Any]:
        with urlopen(Request(f"{base}{path}?{urlencode(query)}", headers=headers), timeout=30.0) as response:
            return json.load(response)

    return fetch


class JiraProject:
    """One Jira project's issues as board tasks, over the workflow `workflow` imported from the site at construction."""

    def __init__(self, fetch: Fetch, project: str, workflow: str) -> None:
        self._fetch = fetch
        self.project = project
        self.machine, self._done = import_workflow(
            fetch("/rest/api/2/workflows/search", {"workflowName": workflow}), workflow
        )
        self._moves = board_moves(self.machine)
        self._lanes = {state["id"] for state in self.machine["states"]}
        self._last: dict[str, BoardTask] = {}
        self._skipped: set[tuple[str, str]] = set()

    def scan(self, put: Callable[[BoardTask], None], retract: Callable[[str], None]) -> None:
        """Publish every issue that is new or changed since the last scan, and retract one the project no longer lists."""
        current: dict[str, BoardTask] = {}
        query = {"jql": f'project = "{self.project}" ORDER BY key ASC', "fields": _FIELDS, "maxResults": "100"}
        while True:
            page = self._fetch("/rest/api/2/search/jql", query)
            for issue in page["issues"]:
                if (task := self._task(issue)) is not None:
                    current[task.id] = task
                    if self._last.get(task.id) != task:
                        put(task)
            if not (token := page.get("nextPageToken")):
                break
            query = {**query, "nextPageToken": token}
        for gone in self._last.keys() - current.keys():
            retract(gone)
        self._last = current

    def _task(self, issue: Mapping[str, Any]) -> BoardTask | None:
        fields = issue["fields"]
        status = fields["status"]["name"]
        lane = lane_id(status)
        if lane not in self._lanes:
            if (issue["key"], status) not in self._skipped:
                self._skipped.add((issue["key"], status))
                logger.warning("%s: status %r is not in the workflow's statuses; issue skipped", issue["key"], status)
            return None
        settled = lane in self._done
        return BoardTask(
            id=issue["key"],
            title=fields["summary"],
            team=fields["project"]["key"],
            lane=lane,
            dependencies=tuple(
                link["inwardIssue"]["key"]
                for link in fields.get("issuelinks") or ()
                if link["type"]["name"] == "Blocks" and "inwardIssue" in link
            ),
            settled="completed" if settled else None,
            created_at=_when(fields.get("created")),
            settled_at=_when(fields.get("resolutiondate")) if settled else None,
            assignee=(fields.get("assignee") or {}).get("displayName", ""),
            labels=tuple(fields.get("labels") or ()),
            description=fields.get("description") or "",
            moves={} if settled else dict(self._moves.get(lane, {})),
        )

    def start(  # pragma: no mutate block — polling thread plumbing
        self, put: Callable[[BoardTask], None], retract: Callable[[str], None], interval: float
    ) -> threading.Thread:
        """Scan now and then every `interval` seconds on a daemon thread, and return it; a failed scan is logged and retried."""

        def run() -> None:
            while True:
                try:
                    self.scan(put, retract)
                except (OSError, ValueError, KeyError) as error:
                    logger.warning("jira %s: scan failed: %s", self.project, error)
                time.sleep(interval)

        thread = threading.Thread(target=run, name="jira", daemon=True)
        thread.start()
        return thread


def open_project(settings: Mapping[str, Any]) -> tuple[JiraProject, str]:
    """The project `settings` names and the site's address, its workflow imported, so the site is read once.

    The token is the environment variable `token_env` (default `JIRA_TOKEN`): a Bearer token, or with `user` the password
    of Basic authentication, as Jira Cloud takes an API token. A setting that cannot work, or a site that does not answer,
    is a `ValueError` saying why.
    """
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    if missing := [key for key in ("url", "project", "workflow") if key not in settings]:
        raise ValueError(f"board: type jira needs {', '.join(missing)}")
    env = str(settings.get("token_env", "JIRA_TOKEN"))
    if not (token := os.environ.get(env, "")):
        raise ValueError(f"board: ${env} holds no Jira token")
    user = settings.get("user")
    authorization = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode() if user else f"Bearer {token}"
    url = str(settings["url"])
    try:
        return JiraProject(http_fetch(url, authorization), str(settings["project"]), str(settings["workflow"])), url
    except OSError as error:
        raise ValueError(f"board: jira site {url}: {error}") from error


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The Board of the Jira project `settings["project"]` on the site `settings["url"]`, polled every `interval` seconds.

    `workflow` names the Jira workflow imported as the Board machine, so building the board reads the site once; see
    `open_project` for the token.
    """
    jira, url = open_project(settings)
    interval = float(settings.get("interval", 30.0))

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        return {"board": jira.machine}

    def start(feed: BoardFeed, group: str, log: EventLog) -> None:
        jira.start(feed.put, feed.retract, interval)

    return Board(machines=machines, start=start, keys=jira_keys(jira.project), source=f"{url} {jira.project}")
