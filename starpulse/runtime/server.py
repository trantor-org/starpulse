"""Serve StarPulse: every lifecycle machine, the tasks in each, and the workflows of each runs adapter instance.

    .venv/bin/python -m starpulse.runtime.server [--host 127.0.0.1] [--port 8766] [--hours 6] [--config starpulse.toml]

Every endpoint, its payload and its refusals are in `docs/serving.md`, "Endpoint reference".
"""

import argparse
import logging
import os
import signal
import socket
import sys
from _thread import interrupt_main
from pathlib import Path

from starpulse.runtime import wiring
from starpulse.runtime.config import Config, rehearsing
from starpulse.runtime.control import control_file
from starpulse.runtime.hold import BOOT_ENV, CLAUDE_CODE_FD_ENV, GITHUB_FD_ENV, LISTEN_FD_ENV, adopted_from_env, boot_token
from starpulse.runtime.listen import held_socket, inherited_socket, listen, listen_options, resolve_listen
from starpulse.runtime.nats_server import bridge_commands
from starpulse.runtime.supervisor import Supervisor, worker_commands
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.runtime.readiness import forget_starts


def serve_parser() -> argparse.ArgumentParser:
    """The `starpulse serve` command line."""
    parser = argparse.ArgumentParser(prog="starpulse serve", description=__doc__.splitlines()[0] if __doc__ else None)
    listen_options(parser)
    parser.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    return parser


def stay_until_stopped() -> None:
    """Block until Ctrl-C or `SIGTERM`: `serve` has no page of its own while a child serves it.

    The wait is a read of the signal wakeup pipe, not an `Event`: the kernel may hand a signal to the supervisor's thread,
    which cannot interrupt a wait in the main thread but does write the pipe."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    woken, wake = os.pipe()
    os.set_blocking(wake, False)
    signal.set_wakeup_fd(wake)
    try:
        while True:
            os.read(woken, 4096)
    except KeyboardInterrupt:
        pass
    finally:
        signal.set_wakeup_fd(-1)
        os.close(woken)
        os.close(wake)


def forget_old_starts(config: Config, args: argparse.Namespace) -> None:
    """Drop the context stamps of the image this one re-executed from; a store it cannot reach is logged, and the page
    then reads the old image's contexts as started until the new ones stamp again."""

    base = args.config.parent if args.config else Path.cwd()
    try:
        forget_starts(database_url(config.database_url, base))
    except Exception:
        logging.getLogger(__name__).warning("serve: cannot drop the old image's context stamps", exc_info=True)


def main(argv: list[str] | None = None) -> None:
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
    if adopted and "contexts" not in adopted:
        forget_old_starts(config, args)
    wiring.prepare(parser, args, config)
    commands = {**worker_commands(args.config), **bridge_commands(config, args.config)}
    if "api" in commands:  # bound once the config is accepted and before the board, the history or a worker starts
        listening = listening or listen(parser, args)
        commands["api"] += ["--hours", str(args.hours)]
    # the contexts child is handed the github webhook and Claude Code OTLP sockets, which outlive it: a delivery or
    # export posted while it is replaced waits in the backlog
    held: dict[str, dict[str, socket.socket]] = {}
    if "contexts" in commands:
        tables = ((GITHUB_FD_ENV, config.github, "github"), (CLAUDE_CODE_FD_ENV, config.claude_code, "claude-code"))
        for env_name, table, what in tables:
            kept = held_socket(os.environ, env_name, table.host, table.port, what) if table else None
            if kept:
                held.setdefault("contexts", {})[env_name] = kept
            os.environ.pop(env_name, None)
    refused: list[str] = []

    def refuse(name: str) -> None:
        refused.append(name)
        interrupt_main()  # wakes `stay_until_stopped`, which stops the other children

    supervisor = Supervisor(
        commands,
        sockets={"api": listening} if "api" in commands else {},
        held=held,
        standby={"contexts", "pulls"},
        warm=180.0,  # the ceiling for the contexts worker (the pulls worker is quicker), which prepares about a minute beside the old one
        control=None if rehearsing() else control_file(args.config),  # a rehearsal must not replace the live endpoint
        limits=config.worker_memory,
        adopted=adopted or None,
        refuse=refuse,
    )
    supervisor.start()
    try:
        stay_until_stopped()
    finally:
        supervisor.stop()
    if refused:  # the child printed the reason on the stderr it shares with this process
        parser.exit(1, f"serve: the {refused[0]} worker refused the config\n")


if __name__ == "__main__":
    main()
