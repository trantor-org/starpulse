"""The Cursor transcript reader's entry point, `python -m starpulse.cursor`; the implementation is in `starpulse.harness_telemetry.cursor`, given the runtime's config loader here."""

from starpulse.harness_telemetry.cursor import main as _main
from starpulse.runtime.config import discover, load

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    _main(argv, discover=discover, load=load)


if __name__ == "__main__":
    main()
