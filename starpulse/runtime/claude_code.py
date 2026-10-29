"""The Claude Code adapter's entry point, `python -m starpulse.runtime.claude_code`: `starpulse.harness_telemetry.adapters.inbound.claude_code` given the runtime's config loader."""

from starpulse.harness_telemetry.adapters.inbound.claude_code import main as _main
from starpulse.runtime.config import discover, load

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    _main(argv, discover=discover, load=load)


if __name__ == "__main__":
    main()
