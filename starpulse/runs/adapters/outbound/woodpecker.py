"""The Woodpecker adapter: each pipeline event of a repository as a workflow, its running pipelines as active runs and its closed ones as recent runs.

`url` is the server's address and the repository (`http://host:8004/owner/name`); the token comes from `WOODPECKER_TOKEN`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from starpulse.contracts.adapters import RunsSink, RunStatus
from starpulse.event_log.event_log import EventLog
from starpulse.runs.adapters.outbound import Unreported

#: The pipeline events shown first, in the order the page lists them; any other event the server reports follows.
EVENTS = ("pull_request", "push", "cron", "manual")

#: Seconds between two listings of the server.
POLL_INTERVAL = 15.0
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


def get(url: str):  # pragma: no mutate block — process boundary
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


class Poller:
    """Reads the server into `Dag` records, remembering what a closed pipeline's detail said."""

    def __init__(self, sink: RunsSink, fetch: Callable[[str], object], url: str) -> None:
        self.sink, self.fetch = sink, fetch
        self.server, self.repo = _split(url)
        self.repo_id: int | None = None
        self.closed: dict[int, dict] = {}  # pipeline number -> its steps and failure, which never change

    def _api(self, path: str):
        return self.fetch(f"{self.server}/api/repos/{path}")

    def _id(self) -> int:
        if self.repo_id is None:
            self.repo_id = self._api(f"lookup/{self.repo}")["id"]
        return self.repo_id

    def _steps(self, number: int) -> dict[str, dict]:
        """Each step of pipeline `number` by name, as the server reports it; a name two workflows share is `workflow/name`."""
        detail = self._api(f"{self._id()}/pipelines/{number}")
        steps = [(w.get("name", ""), c) for w in detail.get("workflows") or [] for c in w.get("children") or []]
        shared = {n for n, count in Counter(c["name"] for _, c in steps).items() if count > 1}
        return {f"{w}/{c['name']}" if c["name"] in shared else c["name"]: c for w, c in steps}

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
        children = self._steps(pipe["number"]) if status == "running" else {}
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
        number = pipe["number"]
        if number not in self.closed:
            failed = _status(pipe["status"]) == "failed"
            children = self._steps(number) if failed else {}
            bad = next((n for n, c in children.items() if _status(c["state"]) == "failed"), None)
            self.closed[number] = {
                "steps": {name: _status(c["state"]) for name, c in children.items()},
                "failure": f"step {bad} exited {children[bad].get('exit_code')}" if bad else None,
            }
        return self.closed[number]

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
        self.closed = {n: seen for n, seen in self.closed.items() if n in {p["number"] for p in pipes}}
        return dags

    def _workflow(self, name: str, pipes: list[dict]) -> dict:
        active = sorted((self._active(p) for p in pipes if _status(p["status"]) in _OPEN), key=lambda r: r["startedAt"])
        closed = [p for p in pipes if _status(p["status"]) not in _OPEN]
        recent = sorted((self._recent(p) for p in closed), key=lambda r: r["finishedAt"], reverse=True)
        latest = max(active, key=lambda run: run["startedAt"]) if active else recent[0] if recent else None
        return {
            "name": name,
            "status": "running" if active else latest["status"] if latest else "not_started",
            "raw": None,
            "runId": latest["runId"] if latest else "",
            "startedAt": latest["startedAt"] if latest else "",
            "finishedAt": "" if active or not latest else latest["finishedAt"],
            "steps": [],
            "schedule": [],
            "stats": None,
            "rerun": None,
            "active": active,
            "recent": recent,
        }

    def read(self) -> None:
        """List the server and hand the workflows to the page; when it cannot be read the last reading stays and the error shows."""
        try:
            self.sink.set_dags(self.listing(), None)
        except OSError as exc:
            self.sink.set_dags(None, str(exc))
        except (ValueError, KeyError, TypeError) as exc:  # an answer not in the shape `listing` reads
            self.sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")


def read(url: str) -> list[dict]:
    """The workflows of the repository at `url`, as the sweeper's `runs` kind compares them with the projection."""
    return Poller(Unreported(), get, url).listing()


def start(url: str) -> None:
    """No start capability: the page never triggers a pipeline, so a workflow has no Run now."""
    return


def follow(url: str, runs: RunsSink, log: EventLog) -> None:  # pragma: no mutate block — thread wiring
    """Show the pipelines of the repository at `url` on `runs`, read again every `POLL_INTERVAL` seconds."""
    poller = Poller(runs, get, url)

    def run() -> None:
        while True:
            poller.read()
            time.sleep(POLL_INTERVAL)

    threading.Thread(target=run, name="woodpecker-runs", daemon=True).start()
