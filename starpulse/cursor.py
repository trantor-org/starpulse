"""The Cursor transcript reader's entry point, `python -m starpulse.cursor`; the implementation is in `starpulse.harness_telemetry.cursor`."""

from starpulse.harness_telemetry.cursor import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
