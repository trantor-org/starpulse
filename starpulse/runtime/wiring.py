"""What `serve` and the workers it supervises build their collaborators from: the config, the run adapters, the
page build and the checks made before anything starts."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, NamedTuple

from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.model.level import Level
from starpulse.flow_metrics.model.level_metrics import RunWindow, WindowPastHistory
from starpulse.flow_metrics.model.trajectories import trajectory_analytics
from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
from starpulse.runs.model import opt_in
from starpulse.runs.model.config import RunsInstance
from starpulse.runtime.config import Config, ConfigError, discover, load, runs_adapter

if (
    TYPE_CHECKING
):  # annotation only: a runtime import would put the scheduler and the page in the Delivery worker's import closure
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog
    from starpulse.flow_metrics.adapters.outbound.history import History
    from starpulse.scheduler.adapters.remote import Remote
    from starpulse.views.adapters.inbound.page_server import PageServer

logger = logging.getLogger(__name__)


_HERE = Path(__file__).parents[1]


#: The Vite build of web/; it holds nothing but the page, so all of it is served.
STATIC = _HERE / "static"


def trajectories_response(
    history: History, query: dict[str, list[str]], level: Level, machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status of the trajectory analytics of the runs that ended in the last `hours` as of `now`, which
    the scheduler ranks tasks by; refused when `hours` is no positive number."""
    from starpulse.flow_metrics.adapters.outbound.history import LevelHistory, SummarisedLevel  # noqa: PLC0415 - the database stack loads when a store does
    from starpulse.views.application.queries.responses import _HEALTH_HOURS, _error, _hours  # noqa: PLC0415 - the scheduler's answer is the page's, and `serve` and the contexts child import no page module
    from starpulse.views.model.encoding import encode  # noqa: PLC0415

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


def read_config(parser: argparse.ArgumentParser, path: Path | None) -> Config:
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


def scheduler_remote(config: Config, base: Path, feed: BoardFeed, log: EventLog, stop: StopEvent) -> Remote:
    """The scheduler `serve` answers `/api/scheduler` from: the `Remote` that reads the status the scheduler worker
    publishes and writes the settings the worker reads. The loop itself runs in that worker, never in `serve`. The status
    follower runs until `stop` is set.

    The scheduler modules are imported here, not at the top, so `starpulse worker pulls` does not load them.
    """
    from starpulse.scheduler.adapters.remote import Remote, follow_status

    follow_status(log, feed, stop)
    return Remote(log)


def serve_until_stopped(server: PageServer, feed: BoardFeed) -> None:
    """Serve until Ctrl-C or `SIGTERM`, then tell every open stream the server is restarting, finish the requests taken
    and save the Board the feed keeps, so the next start resumes from it."""
    try:
        server.run()
    finally:
        feed.save()


class Prepared(NamedTuple):
    """What the config and the environment settle before anything starts: `serve` fails on it before it spawns a child,
    and the Page API is built from it."""

    refresh_token: str | None
    starts: dict[str, Callable[[str], str]]
    reruns: dict[str, Any]
    run_safe: list[str]
    producer_tokens: dict[str, str]
    opt_in_workers: list[str]
    """The `[[runs]]` instances an adapter's own worker runs (`starpulse.runs.model.opt_in`): `serve` runs none of them itself."""


def export_github_token(config: Config) -> None:
    """Export the token `github_token_env` names as `GITHUB_TOKEN` and `GH_TOKEN`, so the GitHub reads and every worker
    sign in with it; `gh` reads `GH_TOKEN` first, which systemd's `EnvironmentFile=` may leave a literal `$VAR` alias.
    Unset, or the variable unset, both are left as they were."""
    token = os.environ.get(config.github_token_env or "")
    if token:
        os.environ["GITHUB_TOKEN"] = os.environ["GH_TOKEN"] = token


def prepare(parser: argparse.ArgumentParser, args: argparse.Namespace, config: Config) -> Prepared:
    """Check `config` and the environment for serving, exiting with the reason when they cannot serve."""
    try:
        producer_tokens = ingest_tokens(config.producers, os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    refresh_token = os.environ.get(config.refresh_token_env or "")
    if config.refresh_token_env and not refresh_token:
        parser.exit(1, f"refresh_token_env: {config.refresh_token_env} is not set\n")
    if config.webhook_command and not os.environ.get(config.webhook_token_env or ""):
        parser.exit(1, f"webhook_token_env: {config.webhook_token_env} is not set\n")
    if not (STATIC / "index.html").is_file():
        parser.exit(1, f"{STATIC} has no build; run `pnpm --filter @starpulse/web build` first\n")
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
