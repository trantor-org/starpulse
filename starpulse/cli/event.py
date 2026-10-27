"""`starpulse event emit`: post one CloudEvent to a server's ingest, as the `[[producers]]` system `--source` names.

    starpulse event emit --source flow --type StepFinished --subject run-1 --data workflow=nightly --data status=failed
    starpulse event emit --source ci-bot --type WORKTREE_READY --subject PROJ-1 --machine in-progress --actor ci

The server is `--url`, else `STARPULSE_WRITE_URL`, else `STARPULSE_URL`. The bearer token is the variable
`STARPULSE_PRODUCER_<SOURCE>_TOKEN` (the source upper-cased, `-` as `_`), unless `--token-env` names another. The
event is `starpulse.contracts.CloudEvent`: the same model the ingest reads, so a field it would refuse is refused here
before anything is sent. Exits 0 when the ingest answers 201, else 1 with the reason on stderr.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from starpulse.cli.agent_wire import DEFAULT_SERVER
from starpulse.contracts.adapters import CloudEvent

__all__ = ["main"]

CONTENT_TYPE = "application/cloudevents+json"


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
    parser.add_argument("--url", help="the server; else STARPULSE_WRITE_URL, STARPULSE_URL")
    parser.add_argument("--token-env", help="the variable holding the token; else STARPULSE_PRODUCER_<SOURCE>_TOKEN")
    return parser


def _data(pairs: Sequence[str]) -> dict[str, str] | None:
    fields = dict(pair.partition("=")[::2] for pair in pairs)
    return fields or None


def _post(url: str, token: str, event: CloudEvent) -> tuple[int, str]:
    request = urllib.request.Request(
        f"{url}/api/machine-events",
        data=event.model_dump_json(exclude_none=True).encode(),
        headers={"Content-Type": CONTENT_TYPE, "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as resp:  # seconds the ingest may take to answer
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:  # before OSError, which it subclasses
        return exc.code, exc.read().decode()
    except OSError as exc:
        return 0, str(exc)


def main(argv: Sequence[str], environ: Mapping[str, str] = os.environ) -> int:
    if not argv or argv[0] != "emit":
        print("usage: starpulse event emit --source S --type T [--subject X] [--data K=V ...]", file=sys.stderr)
        return 2
    args = _parser().parse_args(argv[1:])
    token_env = args.token_env or f"STARPULSE_PRODUCER_{args.source.upper().replace('-', '_')}_TOKEN"
    if not (token := environ.get(token_env)):
        print(f"the token variable {token_env} is not set", file=sys.stderr)
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
    url = (args.url or environ.get("STARPULSE_WRITE_URL") or environ.get("STARPULSE_URL") or DEFAULT_SERVER).rstrip("/")
    status, body = _post(url, token, event)
    if status == 201:
        return 0
    print(f"the ingest at {url} answered {status or 'nothing'}: {body}", file=sys.stderr)
    return 1
