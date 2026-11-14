"""`starpulse subscribe|unsubscribe`: add a subject to, or remove it from, the calling session's JetStream consumer."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from starpulse.bridge.consumers import Consumers
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.subjects import token
from starpulse.bridge.subscriptions import EXPLICIT, explicit_subject
from starpulse.cli.agent_wire import CliError
from starpulse.runtime.config import ConfigError, discover, load
from starpulse.sessions.notify import Registration
from starpulse.sessions.registry import Registry, directory


def bridge(args: argparse.Namespace) -> Any:
    """The config's enabled `[bridge]`, refused when the config is unreadable and unavailable when the bridge is off."""
    try:
        config = load(discover(args.config))
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc
    if not config.bridge.enabled:
        raise CliError("unavailable", "the NATS bridge is off; set `[bridge] enabled = true`")
    return config.bridge


def _target(args: argparse.Namespace, environ: Mapping[str, str]) -> tuple[Publisher, Consumers, str, str]:
    config = bridge(args)
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    try:
        subject = explicit_subject(config.board, args.subject)
    except ValueError as exc:
        raise CliError("refused", str(exc)) from exc
    stream = f"starpulse-{config.board}"
    link = Publisher(f"nats://127.0.0.1:{config.port}", stream, f"starpulse.{config.board}.>")
    return link, Consumers(link, stream), token(session), subject


def _register(args: argparse.Namespace, environ: Mapping[str, str]) -> bool:
    """Record how to reach the calling session, from the inbox the harness gave its process, for the bridge's delivery."""
    socket, secret = environ.get("CLAUDE_CODE_MESSAGING_SOCKET", ""), environ.get("CLAUDE_CODE_MESSAGING_TOKEN", "")
    if not (socket and secret):
        return False
    session = args.session or environ.get("STARPULSE_SESSION", "")
    config = discover(args.config)
    try:
        configured = load(config).bridge.sessions_dir if config else None
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc
    base = config.parent if config else Path.cwd()
    Registry(directory(base, configured)).put(token(session), Registration(session, socket, secret, str(Path.cwd())))
    return True


def _change(args: argparse.Namespace, environ: Mapping[str, str], add: bool) -> dict[str, Any]:
    link, consumers, session, subject = _target(args, environ)
    with closing(link):
        try:
            subscription = consumers.get(session)
            changed = subscription.add(EXPLICIT, [subject]) if add else subscription.remove(subject)
            if changed:
                consumers.put(session, subscription)
        except Unavailable as exc:
            raise CliError("unavailable", f"the NATS server did not answer: {exc}") from exc
    return {"session": session, "subject": subject, "changed": changed, "subjects": subscription.filters}


def subscribe(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changed = _change(args, environ, add=True)
    _register(args, environ)
    return changed


def unsubscribe(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _change(args, environ, add=False)


def register(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Record the calling session's inbox with no subject, so its claim subscriptions reach it (a resumed session
    has a new socket and token); `registered` is false for a process the harness gave no inbox."""
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    return {"session": session, "registered": _register(args, environ)}
