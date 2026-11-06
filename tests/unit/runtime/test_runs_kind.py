from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

from starpulse.event_log.event_log import EventLog
from starpulse.runs.application.queries.projection import PROJECTION
from starpulse.runs.application.queries.reconcile import RESYNC
from starpulse.runtime.assembly import runs_kind
from starpulse.sweeper.passes import Outcome


def _adapter(listed: list[dict]) -> ModuleType:
    return SimpleNamespace(read=lambda url: listed)  # type: ignore[return-value]


def test_the_runs_kind_counts_an_instance_whose_source_differs_from_the_projection(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")
    log.put_state_entry(PROJECTION, "dagu", {"dags": []})
    instance = SimpleNamespace(name="dagu", url="http://dagu")
    adapter = _adapter([{"name": "nightly", "status": "running", "runId": "r1"}])

    kind = runs_kind(log, [(instance, adapter)])

    assert kind.name == "runs"
    assert kind.run() == Outcome(corrected=1, sampled=1)
    assert [entry.fields["instance"] for entry in log.tail(RESYNC, after=0).poll()] == ["dagu"]


def test_an_instance_whose_adapter_has_no_read_is_not_sampled(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")
    instance = SimpleNamespace(name="other", url="u")

    assert runs_kind(log, [(instance, SimpleNamespace())]).run() == Outcome(0, 0)
