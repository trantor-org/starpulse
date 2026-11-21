"""`starpulse github requeue|dismiss <delivery_id>`, `purge`: settle a delivery a consumer left dead (`events` unless
`--consumer` names another).

`requeue` makes it pending again with its attempts spent anew; `dismiss` skips it for good and keeps its last error. Either
clears it from `starpulse_github_dead_rows`. A delivery that is not dead is left as it is and the command exits 1.

`starpulse github purge` takes no delivery: it deletes the consumer's done and skipped rows past their retention, which
the sweeper runs as housekeeping. `starpulse github retire --before <epoch seconds>` skips the consumer's pending
deliveries never tried and saved before then, but a `pulls` merge: a backlog it would only claim to re-read pull
requests.
"""

import argparse
import sys
from pathlib import Path

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse github", description=__doc__)
    parser.add_argument("action", choices=["requeue", "dismiss", "purge", "retire"])
    parser.add_argument("delivery_id", nargs="?", help="the X-GitHub-Delivery id of the dead delivery")
    parser.add_argument("--config", type=Path, help="the starpulse.toml with the [github] table, as `serve` reads it")
    parser.add_argument("--consumer", default="events", help="the inbox consumer whose dead delivery to settle")
    parser.add_argument("--before", type=float, help="retire: the epoch seconds the retired deliveries were saved before")
    args = parser.parse_args(argv)
    whole = args.action in ("purge", "retire")
    if whole == bool(args.delivery_id):
        parser.error("purge and retire take no delivery_id; requeue and dismiss need one")
    if (args.action == "retire") != (args.before is not None):
        parser.error("--before goes with retire alone, which needs it")

    from starpulse.event_log.opening import open_event_log  # noqa: PLC0415 - import cost, paid on first use
    from starpulse.github.adapters.outbound.queue import SqlQueue  # noqa: PLC0415
    from starpulse.pulls.adapters.inbound.pull_deliveries import CONSUMER, URGENT  # noqa: PLC0415
    from starpulse.runtime.config import discover, load  # noqa: PLC0415

    try:
        path = discover(args.config)
        config = load(path)
        if config.github is None:
            raise ValueError("no [github] table in the config")
        log = open_event_log(config.database_url, path)
        urgent = URGENT if args.consumer == CONSUMER else ()  # a retire keeps the merges the backlog holds
        queue = SqlQueue(log.engine, args.consumer, urgent=urgent)
    except (OSError, ValueError) as exc:
        print(f"github: config unreadable: {exc}", file=sys.stderr)
        return 1
    try:
        if args.action == "purge":
            queue.purge()
            print("purge: done")
            return 0
        if args.action == "retire":
            print(f"retire: {queue.retire(args.before)} deliveries of {args.consumer}")
            return 0
        settled = getattr(queue, args.action)(args.delivery_id)
    finally:
        log.close()
    if not settled:
        print(f"github: {args.delivery_id} is not a dead delivery", file=sys.stderr)
        return 1
    print(f"{args.action}: {args.delivery_id}")
    return 0
