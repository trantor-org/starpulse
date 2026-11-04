"""A `SignalFolds` for a test that serves the analytics routes: what is published to it is stored in the signal table
through the adapters' own `TelemetryLog` and folded at once, where a server folds it from the `follow` thread."""

from collections.abc import Iterable
from pathlib import Path

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog
from starpulse.views.adapters.outbound.signal_folds import SignalFolds


class FoldedTelemetry(SignalFolds):
    """`keys` and `analytics` must be the ones the served `Services` and routes use, or the fold rows are stale."""

    def __init__(self, tmp_path: Path, keys: TaskKeys | None, analytics: Analytics | None = None) -> None:
        events = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
        super().__init__(events, keys, analytics)
        self.events = events
        self._published = TelemetryLog(events)

    def publish(self, found: Iterable[Signal]) -> None:
        self._published.publish(found)
        self.catch_up()

    def read(self) -> list[Signal]:
        """Every stored signal, a session at a time."""
        return [s for session in self.sessions() for s in session]
