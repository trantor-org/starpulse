"""The Claude Code adapter's entry point, `python -m starpulse.claude_code`; the implementation is in `starpulse.harness_telemetry.claude_code`, given the runtime's config loader here."""

from starpulse.harness_telemetry.claude_code import main as _main
from starpulse.runtime.config import discover, load

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    _main(argv, discover=discover, load=load)


if __name__ == "__main__":
    main()
