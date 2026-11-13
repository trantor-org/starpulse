"""Serve StarPulse: every lifecycle machine, the tasks in each, and the workflows of each runs adapter instance.

    .venv/bin/python -m starpulse.runtime.server [--host 127.0.0.1] [--port 8766] [--hours 6] [--config starpulse.toml]

Every write (POST /api/..., PUT /api/scheduler, PUT and DELETE /api/history-window) must be `Content-Type: application/json` (else 415) and carry
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
                   `pulls` maps each open task that cites a pull request to [{number, repo (org/repo), url, checks
                   (pass, failing, pending, none), merged, closed (unmerged), conflicting (open and conflicting with its base), queued (open and in the merge queue), merge_sha, merged_at (null until merged), threads (unresolved), behind_main (commits main holds that the head lacks; null once the head branch is gone), stale}], read from
                   GitHub once a minute and held between reads; a failed read keeps the
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
                   `starpulse_task_actor_handoff_seconds` and
                   `starpulse_task_merge_move_seconds` histograms, and the gauges
                   `starpulse_task_actor_heartbeat_timestamp_seconds`, `starpulse_task_actor_recovery_finished` and
                   `starpulse_task_actor_merged_review_waiting`
GET /api/doctor    {ok, checks}: the `cue:` and `repo:` checks of `starpulse doctor` against this server's snapshot and config,
                   each {check, status (pass, warn, fail), reason}, held for a minute; the Ledger's banner reads it.
                   No checks (and ok) when the server runs with no config to check
GET /api/ready     {ready, components}: 200 when the event log is at the schema head, the Board is assembled and every
                   context this `serve` supervises has started, else 503 naming each component (`store`, `board`, `writer`,
                   `contexts`) that is not, each {ready, detail}; reads no task and writes nothing. `starpulse doctor` and
                   `starpulse rehearse` read it
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
                   the Board's flow health from the history's lane changes (`analytics.stay_health`): `states`
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
GET /api/analytics/estimates[?hours=N][&milestone=m-N]
                   each completed task with a `kind-` and `size-` label, over the last `hours`, default 168, as
                   `{now, window_s, estimates}` (`estimates.estimate_report`): each is `{task, milestone, kind, size,
                   profile, steps, active_minutes, effort_size, effort_size_step}`, the label and profile beside the
                   measured steps (a subagent's included) and active minutes (agent seconds plus operator wait).
                   `effort_size` is the smallest `[analytics]` `size_bands` size whose p90 steps and minutes hold
                   them (None past the largest), `effort_size_step` the sizes it lies above (positive) or below the
                   label. `milestone` lists only that milestone's tasks. Refusals as `/api/analytics/steps`
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
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from starpulse.event_log import heartbeat
from starpulse.runtime import launch, wiring
from starpulse.runtime.closure import CONTEXT_ENTRIES, ENTRIES, Reader
from starpulse.runtime.config import Config, rehearsing
from starpulse.runtime.control import control_file
from starpulse.runtime.hold import BOOT_ENV, LISTEN_FD_ENV, STATIC_ENV, adopted_from_env, boot_token
from starpulse.runtime.listen import inherited_socket, listen, listen_options, resolve_listen
from starpulse.runtime.nats_server import bridge_commands
from starpulse.runtime.supervisor import Supervisor, worker_commands
from starpulse.runtime.zygote import Forker

logger = logging.getLogger(__name__)


def serve_parser() -> argparse.ArgumentParser:
    """The `starpulse serve` command line."""
    parser = argparse.ArgumentParser(prog="starpulse serve", description=__doc__.splitlines()[0] if __doc__ else None)
    listen_options(parser)
    parser.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    return parser


def refuse_unassemblable(
    parser: argparse.ArgumentParser, args: argparse.Namespace, config: Config, ready: wiring.Prepared
) -> None:
    """Exit with the reason when the page cannot be built from `config`, so `serve` fails on it as the Page API child would
    rather than supervising a child that exits on it at every start."""
    from sqlalchemy import create_engine  # noqa: PLC0415 - the database stack loads after the config is accepted

    from starpulse.event_log.migrate import StoreNotMigrated, require_migrated  # noqa: PLC0415
    from starpulse.event_log.opening import database_url  # noqa: PLC0415
    from starpulse.board.adapters.upstream_backlog import lane_errors  # noqa: PLC0415
    from starpulse.runtime.assembly import assemble  # noqa: PLC0415

    base = args.config.parent if args.config else Path.cwd()
    try:
        require_migrated(create_engine(database_url(config.database_url, base)))
        assemble(config, base, args.hours * 3600, ready.run_safe)
        for mismatch in lane_errors(config.board_type, config.board, base):
            logger.warning("%s; serving anyway: a state no status names is drawn empty, a status no state names is off the board", mismatch)
    except StoreNotMigrated as exc:
        parser.exit(1, f"{exc}\n")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


#: `machine_sync.REFUSED`, which this module cannot import without loading the database stack.
_ADMISSION_REFUSED = 3
#: `machine_sync.STRANDED`: the Board machine would strand live Tasks, so the active version stays.
_ADMISSION_STRANDED = 4


class StrandedAdmission(ValueError):
    """The Board machine file strands live Tasks; the registry kept the active version."""


def admit_definitions(args: argparse.Namespace) -> None:
    """Register the machine files the config now names, so `serve` starts and reloads only on definitions the registry
    accepts. Runs in a child process: this one never loads the database stack. A ValueError names the States and
    Tasks a missing mapping strands."""
    command = [launch.interpreter(), "-m", "starpulse.runtime.machine_sync"]
    if args.config:
        command += ["--config", str(args.config)]
    ran = subprocess.run(command, capture_output=True, text=True, check=False)
    if ran.returncode == _ADMISSION_STRANDED:
        raise StrandedAdmission(ran.stderr.strip())
    if ran.returncode == _ADMISSION_REFUSED:
        raise ValueError(ran.stderr.strip())
    if ran.returncode:
        raise RuntimeError(f"machine definitions could not be registered:\n{ran.stderr.strip()}")


def admit_at_start(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """`admit_definitions` for the start of `serve`: a Board machine that strands live Tasks is a warning naming them,
    since the registry keeps the active version and the board still reads and serves; any other refusal exits."""
    try:
        admit_definitions(args)
    except StrandedAdmission as exc:
        logger.warning("board machine not activated, serving the active version: %s", exc)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


def stay_until_stopped() -> None:  # pragma: no mutate block — process boundary
    """Block until Ctrl-C or `SIGTERM`: `serve` has no page of its own while a child serves it."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


#: What `api_worker.serve_page` imports once the config is accepted; the preloaded process imports it too, so the Page API child
#: forks with it loaded.
DATABASE_STACK = (
    "starpulse.event_log.event_log",
    "starpulse.flow_metrics.adapters.outbound.history",
    "starpulse.board.board_feed",
    "starpulse.board.claim_refusals",
    "starpulse.board.verdicts",
    "starpulse.board.machine_tasks",
    "starpulse.board.adapters.search",
    "starpulse.pulls.adapters.outbound.pulls",
    "starpulse.runtime.assembly",
)


def forget_old_starts(config: Config, args: argparse.Namespace) -> None:
    """Drop the context stamps of the image this one re-executed from; a store it cannot reach is logged, and the page
    then reads the old image's contexts as started until the new ones stamp again."""
    from starpulse.event_log.opening import database_url  # noqa: PLC0415 - the database stack loads after the config is accepted
    from starpulse.runtime.readiness import forget_starts  # noqa: PLC0415

    base = args.config.parent if args.config else Path.cwd()
    try:
        forget_starts(database_url(config.database_url, base))
    except Exception:
        logging.getLogger(__name__).warning("serve: cannot drop the old image's context stamps", exc_info=True)


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — serve_forever process boundary
    logging.basicConfig(level=logging.INFO)  # the GraphQL cost of each pull request read is an INFO line
    parser = serve_parser()
    args = parser.parse_args(argv)
    config = wiring.read_config(parser, args.config)
    wiring.export_github_token(config)
    resolve_listen(args, config)
    try:
        listening = inherited_socket(os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    os.environ.pop(
        LISTEN_FD_ENV, None
    )  # the workers started below are handed what they hold, not what this process was
    adopted = adopted_from_env(os.environ)  # the children the previous image handed over: the Page API, the contexts
    # one token per start, which each context stamps once it has started; a re-exec that adopts a child keeps the one
    # that child checks, and drops the stamps of the contexts the old image started unless it keeps the contexts child,
    # whose stamps are still true
    os.environ[BOOT_ENV] = boot_token(os.environ, adopted)
    heartbeat.make_directory()  # the workers below beat into it, and the Page API's `/metrics` reads it
    if adopted and "contexts" not in adopted:
        forget_old_starts(config, args)
    ready = wiring.prepare(parser, args, config)
    commands = {**worker_commands(args.config), **bridge_commands(config, args.config)}
    if "api" in commands:  # bound once the config is accepted and before the board, the history or a worker starts
        os.environ[STATIC_ENV] = str(wiring.STATIC)
        listening = listening or listen(parser, args)
        commands["api"] += ["--hours", str(args.hours)]
    admit_at_start(parser, args)
    # the preloaded process inherits the bound socket, so the Page API child forks from it like every other worker
    forker = Forker(
        [*DATABASE_STACK, *(ENTRIES[context] for context in commands), *CONTEXT_ENTRIES],
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
        control=None if rehearsing() else control_file(args.config),  # a rehearsal must not replace the live endpoint
        limits=config.worker_memory,
        admit=lambda: admit_definitions(args),
        adopted=adopted or None,
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
