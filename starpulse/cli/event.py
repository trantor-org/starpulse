"""`starpulse event emit`: publish one CloudEvent to a server's JetStream ingest, as the `[[producers]]` system `--source` names.

    starpulse event emit --source flow --type StepFinished --subject run-1 --data workflow=nightly --data status=failed
    starpulse event emit --source ci-bot --type WORKTREE_READY --subject PROJ-1 --machine in-progress --actor ci

The NATS server is the `[bridge]` `port` and `board` of `--config` (default `starpulse.toml`). The bearer token is the
variable `STARPULSE_PRODUCER_<SOURCE>_TOKEN` (the source upper-cased, `-` as `_`), unless `--token-env` names another.
The event is `starpulse.contracts.CloudEvent`: the same model the ingest reads, so a field it would refuse is refused
here before anything is published. Exits 0 once the stream holds the event, else 1 with the reason on stderr; the server
applies it afterwards, and one it refuses (a machine or actor the producer may not use) is logged there, not answered.
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from starpulse.contracts.adapters import CloudEvent
lazy from starpulse.bridge.ingest import Producer
lazy from starpulse.runtime.config import discover, load

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="starpulse event emit", description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="the producer's name: the CloudEvents `source`")
    parser.add_argument("--type", required=True, help="the event's `type`")
    parser.add_argument("--subject", help="the task (or, for a Step event, the run) the event is for")
    parser.add_argument("--run", help="the run a machine event moved, instead of --subject")
    parser.add_argument("--machine")
    parser.add_argument("--actor")
    parser.add_argument("--id", help="the event id; a fresh one when left out")
    parser.add_argument(
        "--data", action="append", default=[], metavar="KEY=VALUE", help="a text field of `data`; repeats"
    )
    parser.add_argument("--config", type=Path, help="the starpulse.toml naming the [bridge]; default starpulse.toml")
    parser.add_argument("--token-env", help="the variable holding the token; else STARPULSE_PRODUCER_<SOURCE>_TOKEN")
    return parser


def _data(pairs: Sequence[str]) -> dict[str, str] | None:
    fields = dict(pair.partition("=")[::2] for pair in pairs)
    return fields or None


def main(argv: Sequence[str], environ: Mapping[str, str] = os.environ) -> int:
    if not argv or argv[0] != "emit":
        print("usage: starpulse event emit --source S --type T [--subject X] [--data K=V ...]", file=sys.stderr)
        return 2
    args = _parser().parse_args(argv[1:])
    token_env = args.token_env or f"STARPULSE_PRODUCER_{args.source.upper().replace('-', '_')}_TOKEN"
    if not (token := environ.get(token_env)):
        print(
            f"the token variable {token_env} is not set: a producer token belongs to the process that emits, so never"
            " ask a person for it. A session missing a path to emit files that gap as a task and parks on it:"
            " starpulse task park <task> --until-task <gap task>",
            file=sys.stderr,
        )
        return 1
    fields = {
        k: v
        for k, v in {
            "source": args.source,
            "type": args.type,
            "subject": args.subject,
            "run": args.run,
            "machine": args.machine,
            "actor": args.actor,
            "id": args.id,
            "data": _data(args.data),
        }.items()
        if v is not None
    }
    try:
        event = CloudEvent(**fields)
    except ValidationError as invalid:
        print(f"not a CloudEvent: {invalid}", file=sys.stderr)
        return 1

    try:
        bridge = load(discover(args.config)).bridge
    except (OSError, ValueError) as exc:
        print(f"config unreadable: {exc}", file=sys.stderr)
        return 1
    url = f"nats://127.0.0.1:{bridge.port}"
    producer = Producer(url, bridge.board, token)
    try:
        status = producer.post(event.model_dump(mode="json", exclude_none=True))
    finally:
        producer.close()
    if status == 201:
        return 0
    print(f"the ingest at {url} answered {status or 'nothing'}", file=sys.stderr)
    return 1
