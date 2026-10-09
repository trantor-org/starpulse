"""The Claude Code adapter's entry point, `python -m starpulse.claude_code`; the implementation is in `starpulse._internal.harnesses.claude_code`."""

from starpulse._internal.harnesses.claude_code import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
