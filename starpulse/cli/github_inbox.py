"""`starpulse github requeue|dismiss <delivery_id>`: settle a delivery a consumer left dead (`events` unless
`--consumer` names another).

`requeue` makes it pending again with its attempts spent anew; `dismiss` skips it for good and keeps its last error. Either
clears it from `starpulse_github_dead_rows`. A delivery that is not dead is left as it is and the command exits 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse github", description=__doc__)
    parser.add_argument("action", choices=["requeue", "dismiss"])
    parser.add_argument("delivery_id", help="the X-GitHub-Delivery id of the dead delivery")
    parser.add_argument("--config", type=Path, help="the starpulse.toml with the [github] table, as `serve` reads it")
    parser.add_argument("--consumer", default="events", help="the inbox consumer whose dead delivery to settle")
    args = parser.parse_args(argv)

    from starpulse.event_log.migrate import migrate_chain  # noqa: PLC0415 - import cost, paid on first use
    from starpulse.github.adapters.inbound.consumer import open_queue  # noqa: PLC0415
    from starpulse.runtime.config import discover, load  # noqa: PLC0415

    try:
        path = discover(args.config)
        inbox, queue = open_queue(load(path), path.parent if path else Path.cwd(), migrate_chain, args.consumer)
    except (OSError, ValueError) as exc:
        print(f"github: config unreadable: {exc}", file=sys.stderr)
        return 1
    try:
        settled = getattr(queue, args.action)(args.delivery_id)
    finally:
        inbox.engine.dispose()
    if not settled:
        print(f"github: {args.delivery_id} is not a dead delivery", file=sys.stderr)
        return 1
    print(f"{args.action}: {args.delivery_id}")
    return 0
