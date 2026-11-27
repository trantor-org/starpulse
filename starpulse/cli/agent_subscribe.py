"""`starpulse subscribe|unsubscribe`: ask the bridge to add a subject to, or remove it from, the calling session's
JetStream consumer."""

import argparse
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from starpulse.bridge.consumers import Consumers
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.requests import ask
from starpulse.bridge.subjects import stream_subjects, token, wake_subject
from starpulse.bridge.subscriptions import covers, explicit_subject
from starpulse.cli import agent_wire
from starpulse.cli.agent_wire import CliError
from starpulse.runtime.config import ConfigError, discover, load
from starpulse.sessions.ports.notify import Registration
from starpulse.sessions.adapters.outbound.registry import Registry, directory


def bridge(args: argparse.Namespace) -> Any:
    """The config's enabled `[bridge]`, refused when the config is unreadable and unavailable when the bridge is off."""
    try:
        config = load(discover(args.config))
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc
    if not config.bridge.enabled:
        raise CliError("unavailable", "the NATS bridge is off; drop `[bridge] enabled = false`")
    return config.bridge


def _target(args: argparse.Namespace, environ: Mapping[str, str]) -> tuple[Any, str, list[str]]:
    config = bridge(args)
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    try:
        subjects = [explicit_subject(config.board, subject) for subject in args.subject]
    except ValueError as exc:
        raise CliError("refused", str(exc)) from exc
    return config, token(session), subjects


def _registry(config: Path | None, configured: str | None) -> Registry:
    return Registry(directory(config.parent if config else Path.cwd(), configured))


def routed(session: str, config: Path | None = None) -> bool:
    """Whether the bridge's delivery has a route to `session`: a registration under its consumer name, or under the local
    session a claude.ai URL names; without one its events wait on the consumer and no turn starts."""
    found = discover(config)
    try:
        settings = load(found)
        registry = _registry(found, settings.bridge.sessions_dir if found else None)
        local = settings.session_harness().local_id(session)
    except (ConfigError, OSError, ValueError):
        return False
    return any(registry.get(token(name)) for name in filter(None, {session, local}))


def _register(args: argparse.Namespace, environ: Mapping[str, str]) -> bool:
    """Record how to reach the calling session, from the inbox the harness gave its process, for the bridge's delivery."""
    socket, secret = environ.get("CLAUDE_CODE_MESSAGING_SOCKET", ""), environ.get("CLAUDE_CODE_MESSAGING_TOKEN", "")
    if not (socket and secret):
        return False
    own = environ.get("STARPULSE_SESSION", "")
    session = args.session or own
    if session != own:
        return False
    config = discover(args.config)
    try:
        configured = load(config).bridge.sessions_dir if config else None
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc
    _registry(config, configured).put(token(session), Registration(session, socket, secret, str(Path.cwd())))
    _wake_delivery(args)
    return True


def _wake_delivery(args: argparse.Namespace) -> None:
    """Tell the bridge's delivery a route now exists, so events waiting on the session's consumer are handed over; a
    bridge that is off or not answering is started later with its first pass, which finds them."""
    try:
        settings = bridge(args)
        link = Publisher(f"nats://127.0.0.1:{settings.port}", f"starpulse-{settings.board}", stream_subjects(settings.board))
        with closing(link):
            link.signal(wake_subject(settings.board))
    except (CliError, Unavailable, OSError):
        pass


def _change(args: argparse.Namespace, environ: Mapping[str, str], add: bool) -> dict[str, Any]:
    """Ask the bridge to make the change, so it alone writes the consumer and no grant of its own races this one."""
    config, session, subjects = _target(args, environ)
    try:
        answer = ask(f"nats://127.0.0.1:{config.port}", config.board, session, subjects, add)
    except Unavailable as exc:
        raise CliError("unavailable", f"the bridge did not answer: {exc}") from exc
    except ValueError as exc:
        raise CliError("refused", str(exc)) from exc
    return {"session": session, "subject": subjects, "changed": answer["changed"], "subjects": answer["subjects"]}


def subscribe(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changed = _change(args, environ, add=True)
    _register(args, environ)
    return changed


def unsubscribe(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _change(args, environ, add=False)


def register(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Record the calling session's inbox with no subject, so its claim subscriptions reach it (a resumed session
    has a new socket and token); `registered` is false for a process the harness gave no inbox, or a session not its own."""
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    return {"session": session, "registered": _register(args, environ)}


def subscribed(session: str, subject: str, config: Path | None = None) -> bool:
    """Whether the consumer of `session`, or of the local session a claude.ai URL names, filters the board's `subject`;
    False when the bridge is off or unreachable."""
    try:
        settings = bridge(argparse.Namespace(config=config))
        stream = f"starpulse-{settings.board}"
        link = Publisher(f"nats://127.0.0.1:{settings.port}", stream, stream_subjects(settings.board))
        with closing(link):
            consumers = Consumers(link, stream)
            names = filter(None, {session, agent_wire.session_harness(config).local_id(session)})
            filters = [held for name in names for held in consumers.get(token(name)).filters]
    except (CliError, Unavailable, OSError):
        return False
    return any(covers(held, f"starpulse.{settings.board}.{subject}") for held in filters)
