"""The Claude Code adapter's entry point, `python -m starpulse.claude_code`; the implementation is in `starpulse.harness_telemetry.claude_code`."""

from starpulse.harness_telemetry.claude_code import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
