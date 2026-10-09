"""The GitHub Actions adapter: each workflow's job and step graph and latest run, as the `runs` contract's `Dag` records.

`listing` reads one repository (`owner/name`) into those records: a workflow per active workflow file, its jobs (and, for
a job the latest run took once, that job's steps) as the step graph. `start` and `follow` are what a runs adapter module
offers the server for one configured instance. `start` dispatches a workflow that declares `workflow_dispatch` and needs
`GITHUB_TOKEN` or `GH_TOKEN`. `follow` lists the repository, then lists a workflow again for each run entry on the runs
stream (`workflow_run_entry` maps a `workflow_run` webhook to one), and every `RECONCILE_INTERVAL` seconds lists it all.
"""

from __future__ import annotations

import base64
import json
import os
import posixpath
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection
from datetime import datetime
from typing import Any, get_args
from urllib.parse import quote

import yaml

from starpulse._internal.adapters.runs import run_events
from starpulse.contracts.adapters import RunsSink, RunStatus, StartFailedError
from starpulse._internal.store.event_log import DEFAULT_POLL_INTERVAL, EventLog, Tail

#: Each status a run, job or step reports before it completes, and the status it becomes.
#: A run held for a runner, an approval or a protection rule is `queued`; the label itself stays in `raw`.
_STATUS: dict[str, RunStatus] = {
    "requested": "queued",
    "pending": "queued",
    "queued": "queued",
    "waiting": "queued",
    "in_progress": "running",
}

#: Each conclusion a completed run, job or step reports, and the status it becomes.
#: A run that timed out or never started is `failed`; one cancelled, gone stale or left for an approval nobody gave is
#: `aborted`; the label itself stays in `raw`.
_CONCLUSION: dict[str, RunStatus] = {
    "success": "succeeded",
    "neutral": "succeeded",
    "failure": "failed",
    "timed_out": "failed",
    "startup_failure": "failed",
    "cancelled": "aborted",
    "stale": "aborted",
    "action_required": "aborted",
    "skipped": "skipped",
}


def status_of(status: str, conclusion: str | None) -> RunStatus:
    """The status GitHub's `status` and, once `completed`, `conclusion` become; a label GitHub added since is an error,
    never read as a failure."""
    if status == "completed":
        mapped = _CONCLUSION.get(conclusion or "")
    else:
        mapped = None if conclusion else _STATUS.get(status)
    if mapped is None:
        raise ValueError(f"unmapped GitHub Actions status {status!r} with conclusion {conclusion!r}")
    return mapped


#: `(method, path, body)` to the GitHub REST API, answered with the HTTP status and the decoded body.
Transport = Callable[[str, str, dict | None], tuple[int, dict]]

#: What a workflow with several jobs of one name, such as a matrix, reports: the first of these any of them has.
_PRECEDENCE: tuple[RunStatus, ...] = ("failed", "running", "queued", "aborted", "skipped", "succeeded", "not_started")


def _reported(status: str, conclusion: str | None) -> dict[str, Any]:
    """A record's `status`, and its `raw` label (the conclusion once completed) when the status does not already say it."""
    mapped = status_of(status, conclusion)
    label = conclusion if status == "completed" else status
    return {"status": mapped} | ({"raw": label} if label != mapped else {})


class GitHubError(OSError):
    """GitHub answered a read with a status other than 200."""

    def __init__(self, status: int, path: str) -> None:
        super().__init__(f"GitHub answered HTTP {status} for {path}")
        self.status = status


def _get(transport: Transport, path: str) -> dict:
    status, body = transport("GET", path, None)
    if status != 200:
        raise GitHubError(status, path)
    return body


def _definition(transport: Transport, repo: str, path: str) -> dict:
    """The workflow file at `path` on the repository's default branch, parsed; empty when it is not a mapping."""
    content = _get(transport, f"/repos/{repo}/contents/{quote(path)}")["content"]
    document = yaml.safe_load(base64.b64decode(content))
    return document if isinstance(document, dict) else {}


def _jobs(definition: dict) -> list[tuple[str, str, list[str]]]:
    """Each job a workflow file declares: its id, the name a run reports it under, and the ids it needs."""
    declared = definition.get("jobs")
    out = []
    for key, job in (declared if isinstance(declared, dict) else {}).items():
        job = job if isinstance(job, dict) else {}
        name, needs = job.get("name"), job.get("needs") or []
        literal = name if isinstance(name, str) and "${{" not in name else str(key)
        out.append((str(key), literal, [needs] if isinstance(needs, str) else [str(n) for n in needs]))
    return out


def _worst(statuses: list[RunStatus]) -> RunStatus:
    return next(s for s in _PRECEDENCE if s in statuses)


def _graph(definition: dict, ran: list[dict]) -> list[dict]:
    """The step graph of a workflow: its jobs waiting on the jobs they need, each followed by the steps its run took.

    A job's steps are drawn only when exactly one job of the run is that job (a matrix reports one per cell); a job of
    the run the file does not declare, such as one of a reusable workflow, joins the graph waiting on nothing.
    """
    jobs = _jobs(definition)
    named = {key: name for key, name, _ in jobs}
    steps: list[dict] = []
    taken: set[int] = set()
    for key, name, needs in jobs:
        mine = [j for j in ran if j["name"] in (name, key) or j["name"].startswith(f"{name} (")]
        taken.update(j["id"] for j in mine)
        steps.extend(_job_steps(name, [named.get(n, n) for n in needs], mine))
    for job in ran:
        if job["id"] not in taken:
            steps.extend(_job_steps(job["name"], [], [job]))
    return steps


def _job_steps(name: str, depends: list[str], ran: list[dict]) -> list[dict]:
    """A job as one step, and when one job of the run is it, the steps that job took after it in order."""
    if len(ran) == 1:
        state = _reported(ran[0]["status"], ran[0].get("conclusion"))
    elif ran:
        state = {"status": _worst([status_of(j["status"], j.get("conclusion")) for j in ran])}
    else:
        state = {"status": "not_started"}
    out = [{"name": name, "depends": depends, **state, "kind": None}]
    if len(ran) != 1:
        return out
    taken = {name}
    for step in sorted(ran[0].get("steps", []), key=lambda s: s["number"]):
        label = f"{name} / {step['name']}"
        label = label if label not in taken else f"{label} #{step['number']}"
        taken.add(label)
        out.append(
            {
                "name": label,
                "depends": [out[-1]["name"]],
                **_reported(step["status"], step.get("conclusion")),
                "kind": None,
            }
        )
    return out


def listing(transport: Transport, repo: str, only: Collection[str] | None = None) -> tuple[list[dict], list[str]]:
    """Every active workflow of `repo` (`owner/name`), or just those files in `only`, named for its file, with its latest
    run and its job and step graph, and the names of those whose file declares a `workflow_dispatch` trigger."""
    out, startable = [], []
    for workflow in _get(transport, f"/repos/{repo}/actions/workflows?per_page=100")["workflows"]:
        if workflow["state"] != "active" or only is not None and posixpath.basename(workflow["path"]) not in only:
            continue
        runs = _get(transport, f"/repos/{repo}/actions/workflows/{workflow['id']}/runs?per_page=1")["workflow_runs"]
        run = runs[0] if runs else None
        ran = _get(transport, f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"] if run else []
        name = posixpath.basename(workflow["path"])
        try:
            definition = _definition(transport, repo, workflow["path"])
        except GitHubError as exc:  # a GitHub-managed dynamic workflow's path is no file: list it from its run alone
            if exc.status != 404:
                raise
            definition = {}
        if declares_dispatch(definition):
            startable.append(name)
        out.append(
            {
                "name": name,
                **(_reported(run["status"], run.get("conclusion")) if run else {"status": "not_started"}),
                "runId": str(run["id"]) if run else "",
                "startedAt": (run.get("run_started_at") or run["created_at"]) if run else "",
                "finishedAt": run["updated_at"] if run and run["status"] == "completed" else "",
                "steps": _graph(definition, ran),
            }
        )
    return out, startable


def declares_dispatch(definition: dict) -> bool:
    """Whether the workflow file lists `workflow_dispatch` among its triggers, as a name, a list or a mapping."""
    on = definition.get("on", definition.get(True))  # YAML 1.1 reads an unquoted `on` key as true
    return isinstance(on, str | list | dict) and (on == "workflow_dispatch" or "workflow_dispatch" in on)


def connect(token: str | None, timeout: float = 30.0) -> Transport:  # pragma: no mutate block — HTTP boundary
    """A transport to the GitHub API (`GITHUB_API_URL`, else api.github.com), signed in with `token` when there is one."""
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"} | (
        {"Authorization": f"Bearer {token}"} if token else {}
    )

    def send(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        request = urllib.request.Request(
            base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                decoded = json.loads(raw) if raw else {}
                if isinstance(decoded, list):  # a list endpoint's array comes back as `{"items": [...]}`
                    decoded = {"items": decoded}
                return response.status, decoded if isinstance(decoded, dict) else {}
        except urllib.error.HTTPError as exc:
            return exc.code, {}
        except json.JSONDecodeError as exc:
            raise OSError(f"GitHub returned malformed JSON: {exc}") from exc

    return send


def starter(transport: Transport, repo: str) -> Callable[[str], str]:
    """The adapter's start capability: dispatches a workflow of `repo` on its default branch and returns the run's id.

    A workflow whose file declares no `workflow_dispatch` is refused without asking GitHub to run it. GitHub answers a
    dispatch with the run's id only when asked to (`return_run_details`); an answer with none gives an empty id.
    """

    def start(workflow: str) -> str:
        try:
            if not declares_dispatch(_definition(transport, repo, f".github/workflows/{workflow}")):
                raise StartFailedError(f"{workflow} declares no workflow_dispatch trigger")
            ref = _get(transport, f"/repos/{repo}")["default_branch"]
            status, body = transport(
                "POST",
                f"/repos/{repo}/actions/workflows/{quote(workflow, safe='')}/dispatches",
                {"ref": ref, "return_run_details": True},
            )
        except GitHubError as exc:
            raise StartFailedError(f"no workflow {workflow} in {repo}" if exc.status == 404 else str(exc)) from exc
        except OSError as exc:
            raise StartFailedError(f"GitHub unreachable: {exc}") from exc
        if status not in (200, 204):
            raise StartFailedError(f"GitHub refused the dispatch (HTTP {status})")
        return str(body.get("workflow_run_id", ""))

    return start


_REPO = re.compile(r"(?:https://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?")


def repo_of(url: str) -> str:
    """`owner/name` of the repository `url` names, as `owner/name` or its github.com address."""
    match = _REPO.fullmatch(url)
    if match is None:
        raise ValueError(f"{url!r} is not a GitHub repository: use owner/name or https://github.com/owner/name")
    return f"{match[1]}/{match[2]}"


def start(url: str) -> Callable[[str], str] | None:
    """The start capability of the repository at `url`, or None without a token in `GITHUB_TOKEN` or `GH_TOKEN`."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return starter(connect(token), repo_of(url)) if token else None


def _decode(fields: dict) -> tuple[str, float] | None:
    """The workflow and the time an entry of the runs stream reports, or None for one the contract does not allow."""
    try:
        well_formed = fields["phase"] in run_events.PHASES and fields["status"] in get_args(RunStatus)
        return (fields["workflow"], float(fields["time"])) if well_formed else None
    except KeyError, ValueError, TypeError:
        return None


class GitHubRuns:
    """The workflows as the page draws them, from `fetch` (one listing of the repository, or of the named workflows) and
    then run entries.

    The listing is the truth: an entry for a listed workflow reads that workflow again rather than patching it, and an
    unreachable GitHub keeps the workflows last read. Entries and reconnects arrive on the consumer thread and the
    periodic reconcile runs on its own, so the workflows are held under a lock; the sink holds the page-facing state.
    """

    def __init__(
        self,
        sink: RunsSink,
        fetch: Callable[[Collection[str] | None], tuple[list[dict], list[str]]],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sink = sink
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.RLock()
        self._dags: dict[str, dict] = {}
        self._startable: set[str] = set()
        #: When the last listing began; an entry stamped before it is already in that listing.
        self._listed_at = 0.0

    def reconcile(self) -> None:
        """Read the repository once and hand it to the page; when it cannot be read the last reading stays and the error shows."""
        listed_at = self._clock()
        try:
            dags, startable = self._fetch(None)
        except OSError as exc:
            self._sink.set_dags(None, str(exc))
            return
        except (ValueError, KeyError, TypeError, yaml.YAMLError) as exc:  # an answer or a file not in the shape `listing` reads
            self._sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")
            return
        with self._lock:
            self._listed_at = listed_at
            self._dags = {dag["name"]: dag for dag in dags}
            self._startable = set(startable)
            self._sink.set_dags(dags, None, startable=startable)

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Read the workflow an entry reports again; a malformed entry, one the last listing already holds, or one for a
        workflow the repository did not list is dropped, and a workflow GitHub cannot be asked about keeps its state."""
        decoded = _decode(fields)
        with self._lock:
            if decoded is None or decoded[1] < self._listed_at or decoded[0] not in self._dags:
                return
            name = decoded[0]
            try:
                dags, startable = self._fetch({name})
            except OSError, ValueError, KeyError, TypeError, yaml.YAMLError:
                return  # the next reconcile corrects it
            self._dags = {n: next((d for d in dags if d["name"] == n), d) for n, d in self._dags.items()}
            self._startable = (self._startable - {name}) | set(startable)
            self._sink.set_dags(list(self._dags.values()), None, startable=sorted(self._startable))


def workflow_run_entry(payload: dict) -> dict:
    """The runs-stream entry a GitHub `workflow_run` webhook payload reports: the workflow file's run, started or ended."""
    run = payload["workflow_run"]
    status = status_of(run["status"], run.get("conclusion"))
    at = datetime.fromisoformat(run["updated_at"]).timestamp()
    workflow = posixpath.basename(run["path"].split("@")[0])
    phase = "end" if run["status"] == "completed" else "start"
    return run_events.entry(phase, workflow, str(run["id"]), status, now=at)


#: Seconds between two listings of a followed repository; a workflow file added since the last one shows at the next.
RECONCILE_INTERVAL = 60.0


def _reconcile_forever(runs: GitHubRuns) -> None:
    """List the repository every `RECONCILE_INTERVAL` seconds, so a run no entry reported shows all the same."""
    while True:
        runs.reconcile()
        time.sleep(RECONCILE_INTERVAL)


def follow(url: str, runs: RunsSink, log: EventLog, *, interval: float = DEFAULT_POLL_INTERVAL) -> None:
    """Read the repository at `url` into `runs`: its listing, then the run entries the log retains and each new one.

    The listing comes first so an entry stamped before it, already in it, is dropped (`GitHubRuns`). Reads are signed in
    with `GITHUB_TOKEN` or `GH_TOKEN` when one is set; without, GitHub's lower unauthenticated rate limit applies.
    """
    repo = repo_of(url)
    transport = connect(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    reader = GitHubRuns(runs, lambda only=None: listing(transport, repo, only))

    def read() -> None:
        reader.reconcile()
        Tail(log, run_events.STREAM, interval=interval).run(
            lambda entry: reader.handle_entry(str(entry.id), entry.fields), threading.Event()
        )

    threading.Thread(target=read, name="github-runs", daemon=True).start()
    threading.Thread(target=_reconcile_forever, args=(reader,), name="github-runs-reconcile", daemon=True).start()
