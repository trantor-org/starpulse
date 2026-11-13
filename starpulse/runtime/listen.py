"""Where the Page API listens: the options, the socket a parent hands over and the one bound from them."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import stat
from collections.abc import Mapping

from starpulse.contracts.reads import BACKLOG
from starpulse.runtime.config import Config
from starpulse.runtime.hold import LISTEN_FD_ENV

logger = logging.getLogger(__name__)



#: The first file descriptor a service manager passes (`sd_listen_fds(3)`): 0, 1 and 2 are stdio.
_LISTEN_FDS_START = 3


def inherited_socket(environ: Mapping[str, str]) -> socket.socket | None:
    """The listening socket passed in, or `None` to bind `--host` and `--port`.

    A `serve` hands its Page API child, and its own next image when it re-executes, the descriptor `LISTEN_FD_ENV`
    names. Otherwise the service manager's `sd_listen_fds` protocol: `LISTEN_PID` names this process and `LISTEN_FDS`
    counts the sockets, from fd 3. A socket passed to another process, as a child of the unit's would see, is not ours.
    """
    if (handed := environ.get(LISTEN_FD_ENV)) is not None:
        try:
            if not stat.S_ISSOCK(os.fstat(int(handed)).st_mode):
                raise ValueError(f"{LISTEN_FD_ENV}={handed} is not a socket")
        except OSError as exc:
            raise ValueError(f"{LISTEN_FD_ENV}={handed} is not a socket: {exc.strerror}") from exc
        os.set_inheritable(int(handed), False)  # the workers this process starts must not keep it open
        return socket.socket(fileno=int(handed))
    if environ.get("LISTEN_PID") != str(os.getpid()):
        return None
    count = int(environ.get("LISTEN_FDS", "0"))
    if count > 1:
        raise ValueError(f"the service manager passed {count} sockets; serve takes one")
    if count < 1:
        return None
    os.set_inheritable(_LISTEN_FDS_START, False)  # the unit's other processes must not keep it open
    return socket.socket(fileno=_LISTEN_FDS_START)


def listen_options(parser: argparse.ArgumentParser) -> None:
    """Add what the Page API listens on and draws, to the `serve` and `worker api` command lines."""
    parser.add_argument(
        "--host",
        help="the address to listen on; default the config's `host`, else 127.0.0.1, which answers this machine only; "
        "0.0.0.0 answers the network",
    )
    parser.add_argument("--port", type=int, help="the port to listen on; default the config's `port`, else 8766")
    parser.add_argument(
        "--hours",
        type=float,
        help="how far back a task's latest move on a machine counts, Admin's override replaces it; "
        "default the config's `hours`, else 6",
    )


def resolve_listen(args: argparse.Namespace, config: Config) -> None:
    """Fill each listen option no flag gave from `config`, whose own defaults are today's."""
    for option in ("host", "port", "hours"):
        if getattr(args, option) is None:
            setattr(args, option, getattr(config, option))


def listen(parser: argparse.ArgumentParser, args: argparse.Namespace) -> socket.socket:
    """Bind `--host` and `--port`, exiting with the reason when something holds them."""
    try:
        return socket.create_server((args.host, args.port), backlog=BACKLOG)
    except OSError as exc:
        # the errno's own text: `create_server` appends the address the line already names
        reason = os.strerror(exc.errno) if exc.errno and exc.errno > 0 else exc.strerror
        parser.exit(1, f"cannot listen on {args.host}:{args.port}: {reason}; pass --port to serve elsewhere\n")
