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
from starpulse.sessions.registry import DIRECTORY, Registry


def _target(args: argparse.Namespace, environ: Mapping[str, str]) -> tuple[Publisher, Consumers, str, str]:
    try:
        config = load(discover(args.config))
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc
    bridge = config.bridge
    if not bridge.enabled:
        raise CliError("unavailable", "the NATS bridge is off; set `[bridge] enabled = true`")
    session = args.session or environ.get("STARPULSE_SESSION", "")
    if not session:
        raise CliError("usage", "no session; pass `--session` or set `STARPULSE_SESSION`")
    try:
        subject = explicit_subject(bridge.board, args.subject)
    except ValueError as exc:
        raise CliError("refused", str(exc)) from exc
    stream = f"starpulse-{bridge.board}"
    link = Publisher(f"nats://127.0.0.1:{bridge.port}", stream, f"starpulse.{bridge.board}.>")
    return link, Consumers(link, stream), token(session), subject


def _register(args: argparse.Namespace, environ: Mapping[str, str]) -> None:
    """Record how to reach the calling session, from the inbox the harness gave its process, for the bridge's delivery."""
    socket, secret = environ.get("CLAUDE_CODE_MESSAGING_SOCKET", ""), environ.get("CLAUDE_CODE_MESSAGING_TOKEN", "")
    if not (socket and secret):
        return
    session = args.session or environ.get("STARPULSE_SESSION", "")
    config = discover(args.config)
    base = config.parent if config else Path.cwd()
    Registry(base / DIRECTORY).put(token(session), Registration(session, socket, secret, str(Path.cwd())))


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
