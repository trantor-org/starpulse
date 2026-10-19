"""The entry a test's forked child runs in place of `starpulse.__main__.main`: `hold`, `exit N`, `report PATH` or `port PATH`."""

import os
import threading
from pathlib import Path

from starpulse._internal.server.hold import hold
from starpulse._internal.server.server import inherited_socket


def main(argv: list[str]) -> None:
    if argv[0] == "exit":
        raise SystemExit(int(argv[1]))
    if argv[0] == "report":  # the value of the `marker` the preloaded process imported
        import marker  # noqa: PLC0415 - a test's module, on the path only for the test that preloads it

        Path(argv[1]).write_text(marker.VALUE)
    if argv[0] == "port":  # the port of the listening socket the preloaded process handed this child
        Path(argv[1]).write_text(str(inherited_socket(os.environ).getsockname()[1]))
    hold(threading.Event(), print)
