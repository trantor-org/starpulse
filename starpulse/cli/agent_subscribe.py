"""`starpulse subscribe|unsubscribe`: add a subject to, or remove it from, the calling session's JetStream consumer."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import closing
from typing import Any

from starpulse.bridge.consumers import Consumers
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.subjects import token
from starpulse.bridge.subscriptions import EXPLICIT, explicit_subject
from starpulse.cli.agent_wire import CliError
from starpulse.runtime.config import ConfigError, discover, load


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
    return _change(args, environ, add=True)


def unsubscribe(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _change(args, environ, add=False)
