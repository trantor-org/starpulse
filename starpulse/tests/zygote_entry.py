"""The entry a test's forked child runs in place of `starpulse.__main__.main`: `hold`, `exit N` or `report PATH`."""

import threading
from pathlib import Path

from starpulse._internal.server.hold import hold


def main(argv: list[str]) -> None:
    if argv[0] == "exit":
        raise SystemExit(int(argv[1]))
    if argv[0] == "report":  # the value of the `marker` the preloaded process imported
        import marker  # noqa: PLC0415 - a test's module, on the path only for the test that preloads it

        Path(argv[1]).write_text(marker.VALUE)
    hold(threading.Event(), print)
