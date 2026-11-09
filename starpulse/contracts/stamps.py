"""The time stamps StarPulse writes and reads: ISO 8601 text and epoch seconds.

`iso_utc` writes epoch seconds as UTC to the second with a `Z`; `epoch_of` reads ISO 8601 text as epoch seconds and
raises `ValueError` on text it cannot parse. A naive stamp is read in the local zone, as `datetime.timestamp` reads it.
"""

from datetime import UTC, datetime


def iso_utc(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_of(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()
