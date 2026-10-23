"""Serve StarPulse: every lifecycle machine, the tasks in each, and the workflows of each runs adapter instance.

    .venv/bin/python -m starpulse._internal.server.server [--host 127.0.0.1] [--port 8766] [--hours 6] [--config starpulse.toml]

Every write (POST /api/..., PUT /api/autopilot, PUT and DELETE /api/history-window) must be `Content-Type: application/json` (else 415) and carry
no `Origin` or this server's own (else 403), so a web page on another site cannot write through the operator's browser.
It listens on --host, 127.0.0.1 by default.

GET /              the page, built by `pnpm --filter @starpulse/web build` into static/: one view
                   that drills Board → Board state → machine, or Board → workflow. It holds one
                   /api/events connection and nothing else
GET /board, /flow/<name>, /runs
                   the same page; it opens the level that draws that graph, then rewrites the address to /
GET /?demo         the page driven by synthetic agents, for a look without live data
GET /api/events    server-sent events: a `snapshot` on connect ({graphs, dags, pools, flows: [{name,
                   machine, agents}], pulls, settled, error, now}: every machine with its tasks, the
                   workflow declarations, the workflows, each named `<instance>/<workflow>`, and the
                   concurrency pools they run on, each named `<instance>/<pool>`), then
                   a `task` delta ({id, agent, settled}) per Board task change, a `move` delta ({flow, id, agent}) per task a machine placed (the machine:events replay at start sends none: a `snapshot` follows it), a
                   `dags` delta ({dags, pools, error}) per runs change, a `pulls` delta ({pulls}) per
                   change to a task's pull requests and a `claim` delta ({task, reason, at}) per
                   refused agent claim the board adapter reports, with a `: ping` comment every 15 s. A `build` event
                   ({id}: the first 12 hex digits of the SHA-256 of `static/index.html`) follows the `snapshot` on every
                   connect, so a page can tell it is not running the server's build; `restarting` ({at}) goes to every
                   open stream on `SIGTERM`, before the process exits.
                   `pulls` maps each open task that cites a pull request to [{number, url, checks
                   (pass, failing, pending, none), merged, merge_sha, merged_at (null until merged), threads (unresolved), behind_main (commits main holds that the head lacks; null once the head branch is gone), stale}], read from
                   GitHub through `gh` once a minute and held between reads; a failed read keeps the
                   last value with `stale` true.
                   Everything is held in memory: the Board from the configured board adapter, other machines' tasks
                   from machine:events, each instance's workflows from its adapter (`pushed/`: runs:events)
                   `?snapshot=ref` sends the `snapshot` as `ref /api/events/body/<key>`, the path its document is read
                   from, so a browser parses it off its main thread rather than as one long event.
GET /api/events/body/<key>
                   the `snapshot` document a `ref` named, cacheable for an hour (its key is its digest); 404 once the
                   server has built four newer ones
GET /api/snapshot  the document /api/events sends on connect, as one response: without each task's description,
                   criteria and moves (`/api/task/<id>`, `move_sets`) and with only the day's settled tasks;
                   `?view=full` is the whole document, which `starpulse snapshot|board|task` read
GET /api/ledger/<event>[?before=T][&limit=N]
                   {rows, more}: one Ledger's next `limit` rows (default 20, at most 100) older than `before` (epoch
                   seconds, the `at` of the last row held; none: the newest), each as a `LedgerRow`. None is older than
                   24 hours, `more` says whether older ones remain, and rows sharing the boundary second all come in
                   one page, so walking `before` neither repeats nor skips a row. A `before` that is not a finite
                   number, or a `limit` outside 1-100, is 400; an event no workflow is tied to is 404
GET /api/ledger/<event>/events
                   SSE for a page with that Ledger open: `page` ({rows, more}, the newest rows) at once, then `rows`
                   ({rows}, those that are new or differ) as they change. /api/events carries no Ledger row
GET /api/pulls[?repo=OWNER/NAME][&number=N][&state=open|merged|closed][&body_contains=TEXT]
                   {pulls}: the pull requests the PR store holds, kept current by the lifecycle events of the tasks that cite
                   them (and by a read `POST /api/pulls/refresh` asks of GitHub), those matching every filter
                   given, by repository then number, each {repo, number, state (OPEN, MERGED, CLOSED), isDraft,
                   mergeable, baseRefName, headRefOid, body, checks (pass, failing, pending, none: the required
                   checks at the head commit), requiredChecks [{name, result}], threads (unresolved), headRefName
                   (the head branch), unresolvedThreads [{id, author}] (each unresolved thread's id and its first
                   comment's author login, null for a deleted account; the first 100 threads), updatedAt,
                   mergedAt and mergeSha (ISO 8601 UTC merge time and merge commit; null until merged, and for a
                   merge stored before they were kept), and fetchedAt (epoch seconds of the last event or read that changed this record)}. A `number` that is not an integer, or a `state`
                   that is none of those, is 400
GET /metrics       Prometheus text: `starpulse_page_build_info{build}`, 1 for the page build id the `build` event
                   names (none without a build); `starpulse_snapshot_build_seconds_count` and `_sum`, the snapshots built and the
                   seconds they took; `starpulse_board_lane_unattributed_total`, the board:lanes entries
                   any process appended since this one started that name no actor; `starpulse_machine_conformance_violations_total{machine}` and
                   `starpulse_machine_conformance_events_total{machine}`, the recorded moves of each machine that no
                   transition declares and all it judged. Also this process's `process_resident_memory_bytes`,
                   `process_threads`, `process_open_fds` and `process_start_time_seconds`, which moves on every
                   restart. With `[board.actor]`, also `starpulse_task_actor_refusals_total` and the
                   `starpulse_task_actor_latency_seconds`, `starpulse_task_actor_projection_seconds` and
                   `starpulse_task_actor_handoff_seconds` histograms
GET /api/doctor    {ok, checks}: the `cue:` and `repo:` checks of `starpulse doctor` against this server's snapshot and config,
                   each {check, status (pass, warn, fail), reason}, held for a minute; the Ledger's banner reads it.
                   No checks (and ok) when the server runs with no config to check
GET /api/machines[?open=NAME][&before=T][&limit=N]
                   {open, machines, more}: the next `limit` machines (default 20, at most 100) entered from the machine
                   `open` (default the In Progress machine), newest activity first, each whole as a snapshot `flows`
                   entry with its derivation. `before` is the `last` of the last machine held (epoch seconds; none:
                   the newest; a machine with no task counts as 0), machines sharing the boundary activity all come in
                   one page, so walking `before` neither repeats nor skips one. An `open` that is not a machine here is
                   404, a `before` that is not a finite number or a `limit` outside 1-100 is 400
GET /api/done[?before=T][&limit=N]
                   {tasks, more}: the next `limit` done tasks (default and most as `/api/machines`) past their hot day,
                   newest done first, each {id, title, state, model, labels, milestone, type, entered} read from the
                   board on request. `before` is the `entered` of the last one held (epoch seconds; none: the newest).
                   A board that cannot read a task is 404, a bad `before` or `limit` 400
GET /api/history?task=TASK-N[&machine=NAME]
                   {task, path}: the task's Board lane changes as [{at, from, to}], oldest first (`at`
                   epoch seconds). With `flow`, {task, flow, path, steps}: its events on that lifecycle
                   machine as [{at, event, state}] in order, `steps` their count; with `flow`, `task` may be a run id. A task never seen has an empty path; no `task` is 400
                   and an unknown `flow` 404. The machine events are copied from their stream as they
                   arrive into the history database (`database_url`, else starpulse-history.sqlite beside
                   the config), so the path outlives the stream's trim, unless the board adapter keeps
                   its own history. A trim past entries the copy never read is recorded as a gap
GET /api/analytics/health[?hours=N][&stuck_hours=N]
                   the Board's flow health from the history's lane changes (`analytics.board_health`): `states`
                   (each with `wip` now and, for a state that is not final, the `visits`, `mean_s` and `max_s` of
                   its stays over the last `hours`, default 168, `open` of them still going and counted to now),
                   `throughput` {count, per_day} into a final state, `stuck` (tasks in a middle state for
                   `stuck_hours` or longer, default 24, each `counted_to_now`) and `warnings` (the history's
                   recorded gaps). A `hours` or `stuck_hours` that is no positive number is 400; a history that
                   does not keep lane changes for every task is 501
GET /api/analytics/sessions[?hours=N]
                   session and slice health from the harness OTLP exports the Claude Code receiver recorded
                   (`sessions.session_health`, `sessions.slice_health`) over the last `hours`, default 168:
                   `sessions` (one row per harness session and task, with its prompts, requests, tools,
                   rejections and gates, tokens, cost and agent, operator-wait and idle seconds) and `slices` (per task, the
                   sessions that worked it with its interventions, `escalated` and `clean`). A `hours` that is no
                   positive number is 400, as is one longer than the telemetry history (the oldest signal held),
                   with `history_s` its length; a server with no telemetry log is 501 and one that cannot read it 503
GET /api/analytics/steps[?hours=N]
                   every model request of those exports over the last `hours`, default 168, oldest first, as
                   `{now, window_s, steps}` (`steps.session_steps`): each step is `{harness, session, task, at,
                   model, origin, skill, activities, keys, tokens, captured}`, `skill` the skill most recently
                   loaded in its session counting the step's own (`none` before any), `activities` and `keys` one
                   entry per call it made (a key is the redacted shell command, else the tool's name) and
                   `captured` false for Codex. A `hours` that is no positive number is 400, as is one longer than the
                   telemetry history, with `history_s` its length; a server with no telemetry log is 501 and one
                   that cannot read it 503
GET /api/analytics/transitions[?hours=N]
                   the cost of each skill in force within each kind and size, from the steps of those exports over
                   the last `hours`, default 168, as `{now, window_s, transitions}` (`cells.transition_cost`): each is
                   `{kind, size, skill, tasks, steps, side_steps, wasted_steps, wasted_rate, agent_s, peak_context}`,
                   a subagent's steps counted to the task that spawned it. The kind and size are the task's
                   `kind-*` and `size-*` labels; a step of a task without both is in no row. Refusals as
                   `/api/analytics/steps`
GET /api/analytics/cells[?hours=N]
                   the median steps per clean completion of each kind and size over the last `hours`, default 168,
                   as `{now, window_s, cells}` (`cells.cell_report`): each is `{kind, size, n, completions,
                   clean_rate, holdout, median_steps, median_operator_prompts, median_steps_before_edit}`, medians
                   over the latest fifth of the cell's `n` clean completions by end time, except
                   `median_operator_prompts`, over the latest fifth of its `completions`, clean or not. A cell under
                   5 clean completions is not listed. Refusals as `/api/analytics/steps`
GET /api/analytics/graph[?hours=N]
                   the branching directly-follows graph of each skill's transition within each kind and size, from
                   the steps of those exports over the last `hours`, default 168, as `{now, window_s, graph}`
                   (`flow.directly_follows`): each is `{kind, size, skill, source, target, runs, count, share, cut}`,
                   an edge between two activities (`[start]` and `[end]` bound a run) that is `cut` when its source is
                   a judgement cut. Refusals as `/api/analytics/steps`
GET /api/analytics/stages[?hours=N]
                   the sub-stages mined at the judgement cuts of the stretches no skill governs, over the last `hours`
                   and the `hours` before them, as `{now, window_s, stages}` (`flow.sub_stages`): each is `{kind,
                   size, stage, runs, median_activities, previous_runs, previous_median_activities, stability}`.
                   The history must hold twice `hours`, else 400 as for steps. Refusals as `/api/analytics/steps`
GET /api/analytics/diff[?hours=N]
                   each transition's reference run against its slowest clean run over the last `hours`, default 168,
                   as `{now, window_s, diff}` (`flow.fast_slow_diff`): each is `{kind, size, skill, runs, conformant,
                   reference, slow, slow_only, reference_only}`. A transition with under 5 clean runs is not listed;
                   one with none that conforms to its skill's machine is, with `conformant` 0, `reference` null and
                   `reference_only` empty. Refusals as `/api/analytics/steps`
GET /api/analytics/cost-to-go[?hours=N]
                   the expected agent steps to a run's end from each state of each skill machine over the last `hours`,
                   default 168, as `{now, window_s, cost_to_go}` (`flow.cost_to_go`): each is `{kind, size, skill,
                   state, n, cost_to_go}` for a state of the machine or `[start]`, `n` the times the state was seen
                   left in the clean completed runs; every state is listed whatever its `n`. Refusals as
                   `/api/analytics/steps`
GET /api/harnesses  {tiers, harnesses} from the config's `harnesses_file`; both empty with no file
POST /api/machine-events (also gRPC `starpulse.v1.CloudEventsIngest` Publish and PublishBatch on this port, docs/sources.md)
                   post machine events and runs as CloudEvents 1.0 JSON (`application/cloudevents+json`, or a JSON array
                   as `application/cloudevents-batch+json`), with `Authorization: Bearer <token>` of a `[[producers]]`
                   entry; the one write path for both, needing no Redis (docs/sources.md). A machine event is written to
                   `machine:events`; a `StepStarted` or `StepFinished` with no `machine`, `subject` the run's id and
                   `data` {workflow, status[, step, depends]}, to `runs:events`. 201 {accepted}; 400 for an event the
                   contract refuses, 401 for a missing or wrong token, 403 for another producer's source, machine or
                   actor, 413 over the limit, 503 when the log refuses it, 404 when no producer is declared. A batch is
                   checked whole, and a refusal writes nothing. A GET answers 405
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shutil
import signal
import socket
import stat
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, NamedTuple

from starpulse._internal.board.seam import (
    Board,
)
from starpulse._internal.cli import doctor
from starpulse._internal.config.config import Config, ConfigError, RunsInstance, discover, load, runs_adapter
from starpulse._internal.config.level import Level
from starpulse._internal.config.pins import GitHub, LiveBuild, running_commit
from starpulse._internal.eventlog import events as machine_events
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.conformance_monitor import Conformance
from starpulse._internal.eventlog.level_metrics import RunWindow, WindowPastHistory
from starpulse._internal.feed.claim_refusals import CLAIMS_STREAM
from starpulse._internal.feed.history_window import SETTINGS_FILE, HistoryWindow
from starpulse._internal.harnesses.session_start import starter
from starpulse._internal.harnesses.telemetry import TelemetryLog
from starpulse._internal.level.trajectories import trajectory_analytics
from starpulse._internal.pulls.delivery import (
    Projected,
    follow_saves,
    keep_beating,
    metrics_of,
    poller_problem,
    request_refresh,
)
from starpulse._internal.pulls.pull_refresh import PullRefresh
from starpulse._internal.pulls.pull_requests import PullRequests
from starpulse._internal.pulls.pull_store import PullSync
from starpulse._internal.pulls.task_actor import TaskActor, moves_of
from starpulse._internal.pulls.unblock import UNBLOCK_S, Unblocker
from starpulse._internal.runs import opt_in
from starpulse._internal.runs import projection as runs_projection
from starpulse._internal.runs.cloudevents import CloudEventsIngest
from starpulse._internal.runs.ingest import tokens as ingest_tokens
from starpulse._internal.server.asgi_app import _CONTRACT_TTL_S, _cached, page_app
from starpulse._internal.server.closure import ENTRIES, Reader
from starpulse._internal.server.control import control_file
from starpulse._internal.server.encoding import encode, event
from starpulse._internal.server.hold import LISTEN_FD_ENV, STATIC_ENV, announce_ready
from starpulse._internal.server.page_server import BACKLOG, DRAIN_S, PageServer
from starpulse._internal.server.responses import _HEALTH_HOURS, _error, _hours, health_response, history_response  # noqa: F401 - the read routes stay importable from here
from starpulse._internal.server.services import Services
from starpulse._internal.server.supervisor import Supervisor, worker_commands
from starpulse._internal.server.zygote import Forker

logger = logging.getLogger(__name__)


_HERE = Path(__file__).parents[2]


#: The Vite build of web/; it holds nothing but the page, so all of it is served.
_STATIC = _HERE / "static"


#: Seconds an idle event stream waits before a keep-alive comment, which is how a closed page is noticed.
_PING_S = 15.0


#: Seconds a held-task stream lets a burst of changes settle before it rereads the holder's tasks.
_HELD_SETTLE_S = 0.5


if TYPE_CHECKING:  # annotation only: a runtime import would put the autopilot in the Delivery worker's import closure
    from starpulse._internal.autopilot.remote import Remote
    from starpulse._internal.eventlog.event_log import EventLog
    from starpulse._internal.eventlog.history import History
    from starpulse._internal.feed.board_feed import BoardFeed
    from starpulse._internal.pulls.pulls import PullStore


def trajectories_response(
    history: History, query: dict[str, list[str]], level: Level, machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status of the trajectory analytics of the runs that ended in the last `hours` as of `now`, which
    the autopilot ranks tasks by; refused when `hours` is no positive number."""
    from starpulse._internal.eventlog.history import LevelHistory, SummarisedLevel  # noqa: PLC0415 - the database stack loads when a store does

    window = _hours(query, "hours", _HEALTH_HOURS)
    if window is None:
        return _error("hours must be a positive number"), 400
    if not isinstance(history, LevelHistory):
        return _error("this history does not keep every task's trajectory, so it cannot report the level"), 501

    def answer() -> tuple[bytes, int]:
        try:
            if isinstance(history, SummarisedLevel):
                held = history.level_window(level, now=now, window_s=window * 3600)
            else:
                held = RunWindow(history.level_runs(level.machine))
            return (
                encode(
                    "trajectories",
                    trajectory_analytics(
                        level,
                        machines[level.machine],
                        held.runs,
                        now=now,
                        window_s=window * 3600,
                        history_start=held.first,
                        sources=held.sources,
                    ),
                ),
                200,
            )
        except WindowPastHistory as exc:
            return encode("trajectories", {"error": str(exc), "history_s": exc.history_s}), 400

    if not isinstance(history, SummarisedLevel):
        return answer()
    # the query's own params, so a junk param cannot fill the memo
    params = tuple(tuple(query.get(name, ())) for name in ("hours", "from", "to", "p"))
    return history.level_answer(level, ("trajectories", params), now=now, compute=answer)


def _config(parser: argparse.ArgumentParser, path: Path | None) -> Config:
    """The config in `path`, else `starpulse.toml` beside where the view runs, else the defaults."""
    path = discover(path)
    try:
        return load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")


def _adapter(parser: argparse.ArgumentParser, instance: RunsInstance) -> ModuleType:
    """The runs adapter module of `instance`: `start(url)` gives its start capability or None, `follow(url, sink, log)` reads its workflows from the event log and the instance."""
    try:
        return runs_adapter(instance.type)
    except ConfigError as exc:
        parser.exit(1, f"runs instance {instance.name}: {exc}\n")


def run_adapters(parser: argparse.ArgumentParser, config: Config) -> list[tuple[RunsInstance, ModuleType]]:
    """Each `[[runs]]` instance that names a type, with its adapter module (an instance with none is push-only)."""
    return [(instance, _adapter(parser, instance)) for instance in config.runs if instance.type]


def run_starts(adapters: Sequence[tuple[RunsInstance, ModuleType]]) -> dict[str, Callable[[str], str]]:
    """The start capability of each run adapter instance that has one, by instance name."""
    starts = {}
    for instance, adapter in adapters:
        start = adapter.start(instance.url)
        if start:
            starts[instance.name] = start
    return starts


def announce(port: int, hint: str | None) -> None:
    """Say on the terminal where the view is, and the Backlog.md project it found when it did."""
    print(f"StarPulse on :{port}", flush=True)
    if hint:
        print(hint, flush=True)


def autopilot_remote(config: Config, base: Path, feed: BoardFeed, log: EventLog, stop: threading.Event) -> Remote:
    """The autopilot `serve` answers `/api/autopilot` from: the `Remote` that reads the status the autopilot worker
    publishes and writes the settings the worker reads. The loop itself runs in that worker, never in `serve`. The status
    follower runs until `stop` is set.

    The autopilot modules are imported here, not at the top, so `starpulse worker pulls` does not load them.
    """
    from starpulse._internal.autopilot.remote import Remote, follow_status

    follow_status(log, feed, stop)
    return Remote(log, base / (config.autopilot.state_dir or ""))


#: The first file descriptor a service manager passes (`sd_listen_fds(3)`): 0, 1 and 2 are stdio.
_LISTEN_FDS_START = 3


def inherited_socket(environ: Mapping[str, str]) -> socket.socket | None:
    """The listening socket passed in, or `None` to bind `--host` and `--port`.

    A `serve` hands its Page API child, and its own next image when it re-executes, the descriptor `LISTEN_FD_ENV`
    names. Otherwise the service manager's `sd_listen_fds` protocol: `LISTEN_PID` names this process and `LISTEN_FDS`
    counts the sockets, from fd 3. A socket passed to another process, as a child of the unit's would see, is not ours.
    """
    if (handed := environ.get(LISTEN_FD_ENV)) is not None:
        try:
            if not stat.S_ISSOCK(os.fstat(int(handed)).st_mode):
                raise ValueError(f"{LISTEN_FD_ENV}={handed} is not a socket")
        except OSError as exc:
            raise ValueError(f"{LISTEN_FD_ENV}={handed} is not a socket: {exc.strerror}") from exc
        os.set_inheritable(int(handed), False)  # the workers this process starts must not keep it open
        return socket.socket(fileno=int(handed))
    if environ.get("LISTEN_PID") != str(os.getpid()):
        return None
    count = int(environ.get("LISTEN_FDS", "0"))
    if count > 1:
        raise ValueError(f"the service manager passed {count} sockets; serve takes one")
    if count < 1:
        return None
    os.set_inheritable(_LISTEN_FDS_START, False)  # the unit's other processes must not keep it open
    return socket.socket(fileno=_LISTEN_FDS_START)


class EventText:
    """The JSON text of the events last sent, by the data each was made from.

    Every page streaming `/api/events` is handed the same `data` object for a change, and encoding it holds the GIL
    (the `ledgers` event is ~0.7 MB, ~45 ms), so the first page to reach a change encodes it under the lock and the
    others take that text.
    """

    def __init__(self, keep: int = 8) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._made: dict[int, tuple[str, Any, str]] = {}

    def __call__(self, name: str, data: Any) -> str:
        with self._lock:
            made = self._made.get(id(data))
            if made is not None and made[0] == name and made[1] is data:
                return made[2]
            text = event(name, data)
            self._made[id(data)] = (name, data, text)  # holds `data`, so its id is not reused while it is here
            while len(self._made) > self._keep:
                del self._made[next(iter(self._made))]
            return text


def serve_until_stopped(server: PageServer, feed: BoardFeed) -> None:
    """Serve until Ctrl-C or `SIGTERM`, then tell every open stream the server is restarting, finish the requests taken
    and save the Board the feed keeps, so the next start resumes from it."""
    try:
        server.run()
    finally:
        feed.save()


def listen_options(parser: argparse.ArgumentParser) -> None:
    """Add what the Page API listens on and draws, to the `serve` and `worker api` command lines."""
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="the address to listen on; the default answers this machine only, and 0.0.0.0 answers the network",
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--hours",
        type=float,
        default=6.0,
        help="how far back a task's latest move on a machine counts; Admin's override replaces it",
    )


def serve_parser() -> argparse.ArgumentParser:
    """The `starpulse serve` command line."""
    parser = argparse.ArgumentParser(prog="starpulse serve", description=__doc__.splitlines()[0] if __doc__ else None)
    listen_options(parser)
    parser.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    return parser


def _then(first: Callable[[], None], second: Callable[[], None]) -> Callable[[], None]:
    """One callback that runs `first` and then `second`."""

    def both() -> None:
        first()
        second()

    return both


POLL_RESTART_S = (1.0, 60.0)  # the pull poller's first restart delay after a crash and the longest it backs off to


def keep_polling(
    sync: PullSync, stop: threading.Event, running: threading.Event, delay_s: tuple[float, float] = POLL_RESTART_S
) -> None:
    """Run the pull poller until `stop`, with `running` set while it runs, starting it again after a crash with a delay
    that doubles from `delay_s[0]` to `delay_s[1]`, and logging each crash. A run that lasts the longest delay starts
    the backoff over."""
    delay, longest = delay_s
    while not stop.is_set():
        started = time.monotonic()
        running.set()
        try:
            sync.run_forever()
            return
        except Exception:
            logger.exception("pull requests: the poller crashed; restarting in %.0fs", delay)
        finally:
            running.clear()
        stop.wait(delay)
        delay = delay_s[0] if time.monotonic() - started >= longest else min(delay * 2, longest)


def start_delivery(
    config: Config,
    board: Board,
    feed: BoardFeed,
    log: EventLog,
    pulls: PullStore,
    pins: GitHub,
    stop: threading.Event,
    *,
    after_project: Callable[[], None] | None = None,
) -> tuple[TaskActor | None, PullSync | None]:
    """Start the Delivery context: the task actor, the pull store's sync with the projection it feeds, and the
    unblock of dependents, as `config` asks. Returns the actor and the sync, each None when not started.

    The actor records the lane of each write it makes on `feed` (`BoardFeed.record_written`); `after_project` runs
    after each projection. Raises `ValueError` naming a table the board cannot serve.
    """
    from starpulse._internal.ci.ci_trail import CiTrail  # noqa: PLC0415 - the database stack loads when a store does

    # without the GitHub CLI there is no source, and a task simply carries no PR state; a config can turn the store off
    release = config.release
    live = LiveBuild(release.repo, running_commit) if release and release.settle == "release" else None
    actor = None
    if config.task_actor:
        if board.edit is None:
            raise ValueError("[board.actor] needs a board that edits tasks")
        actor = TaskActor(
            feed,
            pulls,
            board.edit,
            board.waits,
            moves_of(feed.machines["board"]),
            config.repos,
            config.release.settle if config.release else None,
            pins,
            evaluate=board.evaluate,
            holds=board.holds,
            live=live,
        )
        actor.start(stop)
    sync = None
    if config.pull_requests and shutil.which("gh"):
        pull_requests = PullRequests(
            feed, pulls, repos=config.repos, pins=pins, trail=CiTrail(log) if config.ci else None
        )
        project = pull_requests.refresh
        if actor:  # the actor reads each save at once and the pins after each projection
            pulls.subscribe(actor.store_changed)
            project = _then(actor.timed_projection(project), actor.pulls_changed)
        if after_project:
            project = _then(project, after_project)
        sync = PullSync(pulls, feed, config.repos, project=project, stop=stop)
        running = threading.Event()
        keep_beating(log, running, stop)
        threading.Thread(target=keep_polling, args=(sync, stop, running), name="pull-store", daemon=True).start()
    if config.release is not None:
        if board.edit is None or not (feed.roles.waiting and feed.roles.ready):
            raise ValueError("[release] needs a board that edits tasks and draws waiting and ready lanes")
        if actor is None:  # the actor merges and unblocks on the facts, so the polling pass would only repeat it
            unblocker = Unblocker(feed, pulls, board.edit, config.repos, config.release.settle, pins, live)
            threading.Thread(
                target=_keep_unblocked, args=(unblocker, feed, stop), name="board-unblock", daemon=True
            ).start()
    return actor, sync


def _keep_unblocked(
    unblocker: Unblocker, feed: BoardFeed, stop: threading.Event, interval_s: float = UNBLOCK_S
) -> None:  # pragma: no mutate block
    """Once the Board replay is done, unblock the Waiting tasks whose dependencies merged every `interval_s` seconds
    until `stop`; a failed pass is logged and never ends the loop."""
    feed.wait_replayed()
    while not stop.is_set():
        try:
            unblocker.unblock()
        except Exception:
            logger.exception("unblock: the pass failed")
        stop.wait(interval_s)


class Prepared(NamedTuple):
    """What the config and the environment settle before anything starts: `serve` fails on it before it spawns a child,
    and the Page API is built from it."""

    refresh_token: str | None
    starts: dict[str, Callable[[str], str]]
    reruns: dict[str, Any]
    run_safe: list[str]
    producer_tokens: dict[str, str]
    opt_in_workers: list[str]
    """The `[[runs]]` instances an opt-in worker runs (`starpulse._internal.runs.opt_in`): none of them runs in `serve`."""


def prepare(parser: argparse.ArgumentParser, args: argparse.Namespace, config: Config) -> Prepared:
    """Check `config` and the environment for serving, exiting with the reason when they cannot serve."""
    try:
        producer_tokens = ingest_tokens(config.producers, os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    refresh_token = os.environ.get(config.refresh_token_env or "")
    if config.refresh_token_env and not refresh_token:
        parser.exit(1, f"refresh_token_env: {config.refresh_token_env} is not set\n")
    if not (_STATIC / "index.html").is_file():
        parser.exit(1, f"{_STATIC} has no build; run `pnpm --filter @starpulse/web build` first\n")
    adapters = run_adapters(parser, config)
    starts = run_starts(adapters)
    # Run now is drawn only for an instance whose adapter can start a run, and only on its run-safe workflows.
    reruns = {
        instance.name: rerun
        for instance, adapter in adapters
        if (factory := getattr(adapter, "rerun", None)) and (rerun := factory(instance.url))
    }
    run_safe = [name for name in config.qualified_run_safe() if name.partition("/")[0] in starts]
    opted_in = [instance.name for instance, adapter in adapters if opt_in.worker_of(adapter)]
    return Prepared(refresh_token, starts, reruns, run_safe, producer_tokens, opted_in)


def refuse_unassemblable(
    parser: argparse.ArgumentParser, args: argparse.Namespace, config: Config, ready: Prepared
) -> None:
    """Exit with the reason when the page cannot be built from `config`, so `serve` fails on it as the Page API child would
    rather than supervising a child that exits on it at every start."""
    from starpulse._internal.server.assembly import assemble  # noqa: PLC0415 - the database stack loads after the config is accepted

    base = args.config.parent if args.config else Path.cwd()
    try:
        assemble(config, base, args.hours * 3600, ready.run_safe)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


def listen(parser: argparse.ArgumentParser, args: argparse.Namespace) -> socket.socket:
    """Bind `--host` and `--port`, exiting with the reason when something holds them."""
    try:
        return socket.create_server((args.host, args.port), backlog=BACKLOG)
    except OSError as exc:
        # the errno's own text: `create_server` appends the address the line already names
        reason = os.strerror(exc.errno) if exc.errno and exc.errno > 0 else exc.strerror
        parser.exit(1, f"cannot listen on {args.host}:{args.port}: {reason}; pass --port to serve elsewhere\n")


def stay_until_stopped() -> None:  # pragma: no mutate block — process boundary
    """Block until Ctrl-C or `SIGTERM`: `serve` has no page of its own while a child serves it."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


def serve_page(  # pragma: no mutate block — serve_forever process boundary
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    config: Config,
    ready: Prepared,
    listening: socket.socket,
) -> None:
    """Build the Page API and serve it on `listening` until stopped: in the `starpulse worker api` child."""

    from starpulse._internal.board import replica  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.eventlog.event_log import EventLog  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.eventlog.history import database_url  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.feed.board_feed import follow  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.feed.claim_refusals import ClaimRefusals  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.feed.machine_tasks import MachineTasks  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.feed.search import SearchIndex  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.pulls.pulls import PullStore  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse._internal.server.assembly import assemble, history_store  # noqa: PLC0415 - the database stack loads after the config is accepted

    refresh_token, starts, reruns, run_safe, producer_tokens, opted_in = ready
    base = args.config.parent if args.config else Path.cwd()
    port = listening.getsockname()[1]
    try:
        board, feed = assemble(config, base, args.hours * 3600, run_safe)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    # Every reader keeps its own cursor over the one event log, so a second copy on another port sees every entry too.
    # The declared --hours is the default; an override Admin wrote beside the config replaces it from the first snapshot.
    url = database_url(config.database_url, base)
    log = EventLog(url)
    window = HistoryWindow(feed, args.hours, log, base / SETTINGS_FILE)
    # the history dates the lanes the board adapter replays, so it is open before the adapter starts
    store = history_store(config, base, feed.machines)
    feed.date_lanes(store.lane_path)
    feed.record_lanes(store)
    # `starpulse worker board` dates when each task's Start Criteria were met; this process rereads the dates it keeps.
    threading.Thread(
        target=feed.follow_criteria, args=(store, threading.Event()), name="criteria-follow", daemon=True
    ).start()
    feed.read_lanes(store.lane_rows)
    # the instance indexes its board for search
    search = SearchIndex.open(log.engine, config.search)
    if search is not None:
        feed.index_tasks(search)  # `starpulse worker search` catches the vectors up off the feed's path
    stop = threading.Event()
    replica.read(board, feed, f"starpulse-{port}", log, config, stop)
    tasks = MachineTasks(feed, board.keys)
    follow(tasks, log, machine_events.STREAM, tasks.handle_entry)
    refusals = ClaimRefusals(feed)
    follow(refusals, log, CLAIMS_STREAM, refusals.handle_entry)
    saved_after = log.head() or 0  # before the store loads: a save between the two is announced past it
    pulls = PullStore(log.engine)
    follow_saves(pulls, log, stop, saved_after)
    pull_refresh = None
    actor_metrics = None
    # `starpulse worker pulls` runs the context, as a child of this process or beside it; this process reads its
    # projection and asks it
    Projected(log, feed).follow(stop)
    # a lane move any writer leaves unnamed is counted
    unattributed = lane_events.Unattributed()
    unattributed.follow(log, stop)
    # a move no transition of its machine declares is counted per machine
    conformance = Conformance(feed.machines)
    conformance.follow(log, stop)
    # `starpulse worker runs` runs the run adapters and the pushed-runs follower; this process
    # draws the workflows that worker keeps in the log, and starts a run only when the page asks; an opt-in
    # worker's instance also shows the page whether that worker is beating
    watched = {name: opt_in.problem(log, name) for name in opted_in}
    runs_projection.Projected(log, feed, watched).follow(stop)
    if config.task_actor:
        actor_metrics = metrics_of(log)
    probes = dataclasses.replace(doctor.LIVE, poller=poller_problem(log))
    if refresh_token:
        pull_refresh = PullRefresh(refresh_token, request_refresh(log, PullSync(pulls, feed, config.repos).tracked))
    announce(port, feed.snapshot()["hint"])
    autopilot_stop = threading.Event()
    autopilot_runtime = autopilot_remote(config, base, feed, log, autopilot_stop)
    from starpulse._internal.pulls.github import GITHUB_MACHINES  # noqa: PLC0415 - the database stack loads after the config is accepted

    cloudevents = (
        CloudEventsIngest(
            {p.name: p for p in config.producers}, producer_tokens, log, {**feed.machines, **GITHUB_MACHINES}
        )
        if producer_tokens
        else None
    )
    services = Services(
        starts=starts,
        run_safe=run_safe,
        reruns=reruns,
        harnesses=config.harnesses,
        start_session=starter(config.session_start_url),
        events=cloudevents,
        autopilot=autopilot_runtime,
        contract=_cached(lambda: doctor.contract(feed.snapshot(), config, probes), _CONTRACT_TTL_S),
        pulls=pulls,
        telemetry=TelemetryLog(log),
        search=search,
        analytics=config.analytics,
        pull_refresh=pull_refresh,
        slow_read_s=config.slow_read_seconds,
        actor_metrics=actor_metrics,
        lane_metrics=unattributed.exposition,
        conformance_metrics=conformance.exposition,
    )
    app = page_app(feed, _STATIC, store, window, board, services)
    try:
        server = PageServer(
            app,
            (args.host, args.port),
            listening,
            tls=config.tls,
            stopping=lambda: feed.announce("restarting", {"at": time.time()}),
            drain_s=DRAIN_S,
        )
        announce_ready(os.environ)
        serve_until_stopped(server, feed)
    finally:
        autopilot_stop.set()
        log.close()
        store.engine.dispose()


#: What `serve_page` imports once the config is accepted; the preloaded process imports it too, so the Page API child
#: forks with it loaded.
DATABASE_STACK = (
    "starpulse._internal.board.replica",
    "starpulse._internal.eventlog.event_log",
    "starpulse._internal.eventlog.history",
    "starpulse._internal.feed.board_feed",
    "starpulse._internal.feed.claim_refusals",
    "starpulse._internal.feed.machine_tasks",
    "starpulse._internal.feed.search",
    "starpulse._internal.pulls.pulls",
    "starpulse._internal.server.assembly",
)


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — serve_forever process boundary
    logging.basicConfig(level=logging.INFO)  # the GraphQL cost of each pull request read is an INFO line
    parser = serve_parser()
    args = parser.parse_args(argv)
    config = _config(parser, args.config)
    try:
        listening = inherited_socket(os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    os.environ.pop(
        LISTEN_FD_ENV, None
    )  # the workers started below are handed what they hold, not what this process was
    ready = prepare(parser, args, config)
    commands = worker_commands(config, args.config)
    if "api" in commands:  # bound once the config is accepted and before the board, the history or a worker starts
        os.environ[STATIC_ENV] = str(_STATIC)
        listening = listening or listen(parser, args)
        commands["api"] += ["--hours", str(args.hours)]
    # the preloaded process inherits the bound socket, so the Page API child forks from it like every other worker
    forker = Forker(
        [*DATABASE_STACK, *(ENTRIES[context] for context in commands)],
        listening=listening if "api" in commands else None,
    )
    if commands:
        forker.start(forked=True)  # once the port is bound: a refused start leaves no process behind
    reader = Reader(args.config)
    supervisor = Supervisor(
        commands,
        sockets={"api": listening} if "api" in commands else {},
        spawn=forker,
        retire=forker.retire,
        read=reader,
        baseline=reader.at_start,
        control=control_file(args.config),
        limits=config.worker_memory,
    )
    supervisor.start()
    try:
        if "api" in commands:  # beside the children, which load the same stack: the page waits on them, not on this
            refuse_unassemblable(parser, args, config, ready)
        stay_until_stopped()
    finally:
        supervisor.stop()
        forker.close()


if __name__ == "__main__":
    main()
