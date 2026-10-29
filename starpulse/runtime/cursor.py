"""The Cursor transcript reader's entry point, `python -m starpulse.runtime.cursor`: `starpulse.harness_telemetry.adapters.outbound.cursor` given the runtime's config loader."""

from starpulse.harness_telemetry.adapters.outbound.cursor import main as _main
from starpulse.runtime.config import discover, load

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    _main(argv, discover=discover, load=load)


if __name__ == "__main__":
    main()
