"""Feed runs: the adapter instances' workflows and their runs per task."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.model.feed.follow import InstanceRuns
from starpulse.board.model.feed.shared import (
    PUSHED_INSTANCE,
)

#: How many of a workflow's newest failed runs the page draws.
FAILED_SHOWN = 10
#: How many of a workflow's newest closed runs, of any status, the page draws.
CLOSED_SHOWN = 8
_ACTIVE = frozenset({"not_started", "queued", "running"})


def _failed(dag: dict) -> dict:
    """`{"failed": [...]}` with the newest failed runs of `dag`'s recent runs (listed newest first), else nothing."""
    failed = [run for run in dag.get("recent") or [] if run.get("status") == "failed"][:FAILED_SHOWN]
    return {"failed": failed} if failed else {}


def _closed(dag: dict) -> dict:
    """`{"closed": [...]}` with the newest runs of `dag`'s recent runs (listed newest first) that are not active, else nothing."""
    closed = [run for run in dag.get("recent") or [] if run.get("status") not in _ACTIVE][:CLOSED_SHOWN]
    return {"closed": closed} if closed else {}


class RunMethods:
    def runs(self, instance: str) -> InstanceRuns:
        """Where the runs adapter instance `instance` publishes its workflows."""
        return InstanceRuns(self, instance)

    def set_dags(
        self,
        instance: str,
        dags: list | None,
        error: str | None,
        pools: list | None = None,
    ) -> None:
        """Take the latest workflows and concurrency pools of `instance` (None keeps the last of each) and publish
        them when they differ from before; an empty `pools` says the instance now reports none.
        """
        with self._lock:
            dags = self._dags.get(instance, []) if dags is None else dags
            pools = self._pools.get(instance, []) if pools is None else pools
            moved = (dags, error, pools) != (
                self._dags.get(instance),
                self._runs_errors.get(instance),
                self._pools.get(instance, []),
            )
            if not moved:
                return
            tied = {dag for dags_ in self._ties.values() for dag in dags_}
            runs_moved = self._tied_runs(instance, dags, tied) != self._tied_runs(
                instance, self._dags.get(instance, []), tied
            )
            self._dags[instance] = dags
            self._pools[instance] = pools
            if error is None:
                self._runs_errors.pop(instance, None)
            else:
                self._runs_errors[instance] = error
            self._workflow_rows = self._workflows()
            self._publish("dags", {"dags": self._workflow_rows, "pools": self._drawn_pools(), "error": self._error()})
        if runs_moved:
            self._refresh_ledgers()

    @staticmethod
    def _tied_runs(instance: str, dags: list, tied: set[str]) -> dict[str, list]:
        """The recent runs of the workflows of `instance` that an event ties: all the Ledger reads of its workflows."""
        return {
            f"{instance}/{dag['name']}": dag.get("recent", []) for dag in dags if f"{instance}/{dag['name']}" in tied
        }

    def _workflows(self) -> list[dict]:
        """Every instance's workflows, each named `<instance>/<workflow>`; a pushed one an adapter lists, by its bare name
        or as the `<instance>/<workflow>` an ingested one is named, is drawn by that adapter."""
        adapters = [(i, dag["name"]) for i, dags in self._dags.items() if i != PUSHED_INSTANCE for dag in dags]
        listed = {name for _, name in adapters} | {f"{i}/{name}" for i, name in adapters}
        return [
            {
                **{key: value for key, value in dag.items() if key != "recent"},
                "name": f"{instance}/{dag['name']}",
                "startUrl": self._start_urls.get(instance, ""),
            }
            | ({"pool": f"{instance}/{dag['pool']}"} if dag.get("pool") else {})
            | _failed(dag)
            | _closed(dag)
            for instance, dags in self._dags.items()
            for dag in dags
            if instance != PUSHED_INSTANCE or dag["name"] not in listed
        ]
