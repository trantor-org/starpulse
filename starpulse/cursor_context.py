"""The Cursor context-limit reset's entry point, `python -m starpulse.cursor_context`; the implementation is in `starpulse.harness_telemetry.cursor_context`, given the Sessions session starter and the runtime's config loader here."""

from starpulse.harness_telemetry.cursor_context import main as _main
from starpulse.runtime.config import discover, load
from starpulse.sessions.session_start import starter

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    _main(starter, argv, discover=discover, load=load)


if __name__ == "__main__":
    main()
