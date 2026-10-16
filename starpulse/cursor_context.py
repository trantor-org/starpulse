"""The Cursor context-limit reset's entry point, `python -m starpulse.cursor_context`; the implementation is in `starpulse._internal.harnesses.cursor_context`."""

from starpulse._internal.harnesses.cursor_context import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
