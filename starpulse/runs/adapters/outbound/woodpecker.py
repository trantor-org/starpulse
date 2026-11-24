"""The Woodpecker adapter: each pipeline event of a repository as a workflow, its running pipelines as active runs and its closed ones as recent runs.

`url` is the server's address and the repository (`http://host:8004/owner/name`); the token comes from `WOODPECKER_TOKEN`.
"""

import base64
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

import yaml

from starpulse.contracts.adapters import RunsSink, RunStatus
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.runs.adapters.outbound import Unreported, node
from starpulse.runs.adapters.outbound.resync import follow_resync

#: The pipeline events shown first, in the order the page lists them; any other event the server reports follows.
EVENTS = ("pull_request", "push", "cron", "manual")

#: The worker that runs this adapter (`starpulse.runs.model.opt_in`): `serve` supervises it as a child.
WORKER = "woodpecker"

#: How many of the repository's newest pipelines each listing asks for.
PIPELINE_LIMIT = 60
_TIMEOUT = 10.0
_TASK = re.compile(r"TASK-\d+", re.IGNORECASE)
_PULL = re.compile(r"^refs/pull/(\d+)/")
_STATUS: dict[str, RunStatus] = {
    "running": "running",
    "pending": "queued",
    "blocked": "queued",
    "success": "succeeded",
    "failure": "failed",
    "error": "failed",
    "killed": "aborted",
    "canceled": "aborted",
    "declined": "aborted",
    "skipped": "skipped",
}
_OPEN = ("running", "queued")


def request(url: str) -> urllib.request.Request:
    """A GET of `url` carrying the server's token from `WOODPECKER_TOKEN`."""
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ.get('WOODPECKER_TOKEN', '')}"})


def get(url: str):
    """The JSON the server at `url` answers; a failure to reach it raises `OSError`."""
    with urllib.request.urlopen(request(url), timeout=_TIMEOUT) as response:
        return json.load(response)


def _iso(epoch: int | None) -> str:
    """A server epoch second as ISO 8601 UTC to the second, or empty when it has none."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if epoch else ""


def _status(name: str) -> RunStatus:
    return _STATUS.get(name, "failed")


def _task(pipe: dict) -> str | None:
    found = _TASK.search(f"{pipe.get('refspec', '')} {pipe.get('title', '')}")
    return found[0].upper() if found else None


def _pull(pipe: dict) -> int | None:
    found = _PULL.match(pipe.get("ref", ""))
    return int(found[1]) if found else None


def _split(url: str) -> tuple[str, str]:
    """The server's base address and the `owner/name` of the repository in `url`."""
    parts = urllib.parse.urlsplit(url)
    repo = parts.path.strip("/")
    if repo.count("/") != 1:
        raise ValueError(f"woodpecker url {url!r} must end in the repository, owner/name")
    return f"{parts.scheme}://{parts.netloc}", repo


def _nodes(workflows: list[dict], needs: dict[str, list[str]]) -> list[dict]:
    """The graph of a pipeline: a node per workflow, waiting on the workflows its file names, and per non-service step.

    A step waits on its `depends_on`; one with none waits on the clone step (or the workflow) when a sibling declares
    `depends_on`, and otherwise the steps chain in the order they run. Any field missing raises `KeyError`.
    """
    names = {w["name"] for w in workflows}
    out = []
    for w in workflows:
        wf = w["name"]
        out.append(node(wf, [d for d in needs.get(wf, []) if d in names], _status(w["state"])))
        steps = sorted(
            (c for c in w.get("children") or [] if c.get("type") != "service"), key=lambda c: c.get("pid", 0)
        )
        waits = any(c.get("depends_on") for c in steps)
        known = {c["name"] for c in steps}
        clone = next((f"{wf} / {c['name']}" for c in steps if c.get("type") == "clone"), wf)
        before = wf
        for c in steps:
            label = f"{wf} / {c['name']}"
            declared = [f"{wf} / {d}" for d in c.get("depends_on") or [] if d in known and d != c["name"]]
            ahead = [before] if not waits or c.get("type") == "clone" else declared or [clone]
            out.append(node(label, ahead, _status(c["state"])))
            before = label
    return out


class Poller:
    """Reads the server into `Dag` records, remembering what a closed pipeline's detail said."""

    def __init__(self, sink: RunsSink, fetch: Callable[[str], object], url: str) -> None:
        self.sink, self.fetch = sink, fetch
        self.server, self.repo = _split(url)
        self.repo_id: int | None = None
        self._reading = threading.Lock()
        self.seen: dict[
            tuple[int, str], dict
        ] = {}  # (pipeline number, status) -> its detail; a closed one never changes
        self.needs: dict[
            int, dict[str, list[str]]
        ] = {}  # pipeline number -> the workflows each workflow's file waits on

    def _api(self, path: str):
        return self.fetch(f"{self.server}/api/repos/{path}")

    def _id(self) -> int:
        if self.repo_id is None:
            self.repo_id = self._api(f"lookup/{self.repo}")["id"]
        return self.repo_id

    def _detail(self, pipe: dict) -> dict:
        key = (pipe["number"], pipe["status"])
        if key not in self.seen:
            self.seen[key] = self._api(f"{self._id()}/pipelines/{pipe['number']}")
        return self.seen[key]

    def _steps(self, pipe: dict) -> dict[str, dict]:
        """Each step of `pipe` as the server reports it, by `workflow / step`; a service container is no step."""
        return {
            f"{w['name']} / {c['name']}": c
            for w in self._detail(pipe).get("workflows") or []
            for c in w.get("children") or []
            if c.get("type") != "service"
        }

    def _needs(self, number: int) -> dict[str, list[str]]:
        if number not in self.needs:
            files = self._api(f"{self._id()}/pipelines/{number}/config")
            loaded = {
                f["name"]: yaml.safe_load(base64.b64decode(f["data"], validate=True)).get("depends_on") or []
                for f in files
            }
            self.needs[number] = {n: [d] if isinstance(d, str) else d for n, d in loaded.items()}
        return self.needs[number]

    def _graph(self, pipe: dict | None) -> list[dict]:
        """The nodes of the pipeline `pipe`, or none when the server cannot give or the adapter cannot read them: the page then lists the run."""
        if pipe is None:
            return []
        try:
            workflows = self._detail(pipe).get("workflows") or []
            return _nodes(workflows, self._needs(pipe["number"]) if len(workflows) > 1 else {})
        except OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError:
            return []

    def _base(self, pipe: dict) -> dict:
        number = pipe["number"]
        return {
            "runId": str(number),
            "task": _task(pipe),
            "pr": _pull(pipe),
            "commit": pipe.get("commit") or None,
            "url": f"{self.server}/repos/{self._id()}/pipeline/{number}",
            "startedAt": _iso(pipe.get("started") or pipe.get("created")),
        }

    def _active(self, pipe: dict) -> dict:
        status = _status(pipe["status"])
        children = self._steps(pipe) if status == "running" else {}
        running = [name for name, c in children.items() if _status(c["state"]) == "running"]
        return {
            **self._base(pipe),
            "status": status,
            "raw": None,
            "step": running[-1] if running else "",
            "stepStartedAt": _iso(children[running[-1]].get("started")) if running else "",
            "steps": {name: _status(c["state"]) for name, c in children.items()},
            "attempt": None,
            "failure": None,
        }

    def _details(self, pipe: dict) -> dict:
        children = self._steps(pipe) if _status(pipe["status"]) == "failed" else {}
        bad = next((n for n, c in children.items() if _status(c["state"]) == "failed"), None)
        return {
            "steps": {name: _status(c["state"]) for name, c in children.items()},
            "failure": f"step {bad} exited {children[bad].get('exit_code')}" if bad else None,
        }

    def _recent(self, pipe: dict) -> dict:
        return {
            **self._base(pipe),
            "status": _status(pipe["status"]),
            "raw": pipe["status"],
            "finishedAt": _iso(pipe.get("finished")),
            "params": {},
            "attempt": None,
            **self._details(pipe),
        }

    def listing(self) -> list[dict]:
        """One workflow per pipeline event with its running pipelines and its newest closed ones."""
        pipes = self._api(f"{self._id()}/pipelines?perPage={PIPELINE_LIMIT}")
        events = [*EVENTS, *sorted({p["event"] for p in pipes} - set(EVENTS))]
        dags = [self._workflow(name, [p for p in pipes if p["event"] == name]) for name in events]
        shut = {(p["number"], p["status"]) for p in pipes if _status(p["status"]) not in _OPEN}
        self.seen = {k: v for k, v in self.seen.items() if k in shut}
        self.needs = {n: v for n, v in self.needs.items() if n in {p["number"] for p in pipes}}
        return dags

    def _workflow(self, name: str, pipes: list[dict]) -> dict:
        active = sorted((self._active(p) for p in pipes if _status(p["status"]) in _OPEN), key=lambda r: r["startedAt"])
        closed = [p for p in pipes if _status(p["status"]) not in _OPEN]
        recent = sorted((self._recent(p) for p in closed), key=lambda r: r["finishedAt"], reverse=True)
        latest = max(active, key=lambda run: run["startedAt"]) if active else recent[0] if recent else None
        shown = (active or recent)[:1]
        drawn = next((p for p in pipes if str(p["number"]) == shown[0]["runId"]), None) if shown else None
        return {
            "name": name,
            "status": "running" if active else latest["status"] if latest else "not_started",
            "raw": None,
            "runId": latest["runId"] if latest else "",
            "startedAt": latest["startedAt"] if latest else "",
            "finishedAt": "" if active or not latest else latest["finishedAt"],
            "steps": self._graph(drawn),
            "schedule": [],
            "stats": None,
            "rerun": None,
            "active": active,
            "recent": recent,
        }

    def read(self) -> None:
        """List the server and hand the workflows to the page; when it cannot be read the last reading stays and the error shows."""
        with self._reading:  # the start's read and a resync's never overlap, so the older listing never publishes last
            try:
                self.sink.set_dags(self.listing(), None)
            except OSError as exc:
                self.sink.set_dags(None, str(exc))
            except (ValueError, KeyError, TypeError) as exc:  # an answer not in the shape `listing` reads
                self.sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")


def read(url: str) -> list[dict]:
    """The workflows of the repository at `url`, as the sweeper's `runs` kind compares them with the projection."""
    return Poller(Unreported(), get, url).listing()


def follow(url: str, runs: RunsSink, log: EventLog, stop: StopEvent | None = None) -> None:
    """Show the pipelines of the repository at `url` on `runs`: listed once now, then again for each `runs:resync` entry
    naming the instance (`follow_resync`), which a commit status Woodpecker posts writes (`runs.adapters.inbound.status_resync`)."""
    poller = Poller(runs, get, url)
    follow_resync(log, getattr(runs, "instance", None) or "", poller.read, stop or StopEvent())
    threading.Thread(target=poller.read, name="woodpecker-runs", daemon=True).start()
