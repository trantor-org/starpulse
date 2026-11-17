"""`starpulse subscribe|unsubscribe`: add a subject to, or remove it from, the calling session's JetStream consumer."""

import argparse
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from starpulse.bridge.consumers import Consumers
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.subjects import token
from starpulse.bridge.subscriptions import EXPLICIT, covers, explicit_subject
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


def _target(args: argparse.Namespace, environ: Mapping[str, str]) -> tuple[Publisher, Consumers, str, list[str]]:
    config = bridge(args)
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    try:
        subjects = [explicit_subject(config.board, subject) for subject in args.subject]
    except ValueError as exc:
        raise CliError("refused", str(exc)) from exc
    stream = f"starpulse-{config.board}"
    link = Publisher(f"nats://127.0.0.1:{config.port}", stream, f"starpulse.{config.board}.>")
    return link, Consumers(link, stream), token(session), subjects


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
    base = config.parent if config else Path.cwd()
    Registry(directory(base, configured)).put(token(session), Registration(session, socket, secret, str(Path.cwd())))
    return True


def _change(args: argparse.Namespace, environ: Mapping[str, str], add: bool) -> dict[str, Any]:
    link, consumers, session, subjects = _target(args, environ)
    with closing(link):
        try:
            subscription = consumers.get(session)
            if add:
                changed = subscription.add(EXPLICIT, subjects)
            else:
                removed = [subscription.remove(subject) for subject in subjects]
                changed = any(removed)
            if changed:
                consumers.put(session, subscription)
        except Unavailable as exc:
            raise CliError("unavailable", f"the NATS server did not answer: {exc}") from exc
    return {"session": session, "subject": subjects, "changed": changed, "subjects": subscription.filters}


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
    """Whether `session`'s consumer filters cover the board's `subject`; False when the bridge is off or unreachable."""
    try:
        settings = bridge(argparse.Namespace(config=config))
        stream = f"starpulse-{settings.board}"
        link = Publisher(f"nats://127.0.0.1:{settings.port}", stream, f"starpulse.{settings.board}.>")
        with closing(link):
            filters = Consumers(link, stream).get(token(session)).filters
    except (CliError, Unavailable, OSError):
        return False
    return any(covers(held, f"starpulse.{settings.board}.{subject}") for held in filters)
