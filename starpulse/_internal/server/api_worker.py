"""`starpulse worker api`: the Page API as its own process, a child `serve` supervises.

`serve` binds the listening socket and hands it to this child on the descriptor `STARPULSE_LISTEN_FD` names
(`starpulse._internal.server.hold.LISTEN_FD_ENV`), so a connection made while the child is being replaced waits in the
socket's backlog for the next one rather than being refused. The child builds the page as `serve` once did: it reads the
Board from the replica the Board child publishes and starts no adapter watcher. Started by hand, without a handed
socket, it binds `--host` and `--port` itself.

`SIGTERM` finishes the requests it took (`serve_until_stopped`) and saves the Board it keeps; a config change replaces
the process, as the page is built from the whole config once.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from starpulse._internal.config.config import Config
from starpulse._internal.server import server
from starpulse._internal.server.hold import LISTEN_FD_ENV, STATIC_ENV
from starpulse._internal.server.server import _config, inherited_socket, listen, prepare, serve_page


def built_blocks(config: Config) -> tuple:
    """What of `config` the page is built from at start; a change needs a new process."""
    return (config,)


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    config = _config(parser, args.config)
    if static := os.environ.get(STATIC_ENV):
        server._STATIC = Path(static)
    ready = prepare(parser, args, config)
    try:
        listening = inherited_socket(os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    os.environ.pop(LISTEN_FD_ENV, None)
    serve_page(parser, args, config, ready, listening or listen(parser, args))
