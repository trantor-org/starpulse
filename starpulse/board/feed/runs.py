"""Feed runs: the adapter instances' workflows and their runs per task."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.feed.follow import InstanceRuns
from starpulse.board.feed.shared import (
    PUSHED_INSTANCE,
    is_cold,
)


#: How many of a workflow's newest failed runs the page draws.
FAILED_SHOWN = 10


def _failed(dag: dict) -> dict:
    """`{"failed": [...]}` with the newest failed runs of `dag`'s recent runs (listed newest first), else nothing."""
    failed = [run for run in dag.get("recent") or [] if run.get("status") == "failed"][:FAILED_SHOWN]
    return {"failed": failed} if failed else {}


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
        startable: list[str] | None = None,
        cpu: dict | None = None,
    ) -> None:
        """Take the latest workflows and concurrency pools of `instance` (None keeps the last of each) and publish
        them when they differ from before; an empty `pools` says the instance now reports none.

        `cpu` is the instance's latest CPU reading (None keeps the last).

        `startable` names the workflows of `instance` its adapter can start now (None keeps the last report; an
        instance that never reports one can start every workflow it has a start for). Run now is declared only on a
        `run_safe` workflow in it, and a change hands every page a snapshot, which is what carries the declaration.
        """
        with self._lock:
            dags = self._dags.get(instance, []) if dags is None else dags
            pools = self._pools.get(instance, []) if pools is None else pools
            cpu = self._cpu.get(instance) if cpu is None else cpu
            reported = self._startable.get(instance) if startable is None else frozenset(startable)
            moved = (dags, error, pools, cpu) != (
                self._dags.get(instance),
                self._runs_errors.get(instance),
                self._pools.get(instance, []),
                self._cpu.get(instance),
            )
            changed = reported != self._startable.get(instance)
            if not (moved or changed):
                return
            tied = {dag for dags_ in self._ties.values() for dag in dags_}
            runs_moved = moved and self._tied_runs(instance, dags, tied) != self._tied_runs(
                instance, self._dags.get(instance, []), tied
            )
            self._dags[instance] = dags
            self._pools[instance] = pools
            if cpu is not None:
                self._cpu[instance] = cpu
            if reported is not None:
                self._startable[instance] = reported
            if error is None:
                self._runs_errors.pop(instance, None)
            else:
                self._runs_errors[instance] = error
            if moved:
                self._publish(
                    "dags",
                    {"dags": self._workflows(), "pools": self._drawn_pools(), "cpu": dict(self._cpu), "error": self._error()},
                )
                self._attach_runs()
            if changed:
                self._publish("snapshot", self.snapshot())
        if runs_moved:
            self._refresh_ledgers()

    def _task_runs(self) -> dict[str, list[dict]]:
        """The linked runs among every instance's recent runs, by the task their run id names."""
        out: dict[str, list[dict]] = {}
        for dags in self._dags.values():
            for run in (run for dag in dags for run in dag.get("recent", [])):
                if run.get("task") and run.get("url"):
                    out.setdefault(run["task"], []).append(
                        {"url": run["url"], "status": run["status"], "startedAt": run["startedAt"]}
                    )
        return out

    def _attach_runs(self) -> None:
        """Give each open task the runs `_task_runs` finds for it and publish those whose runs changed."""
        by_task = self._task_runs()
        for task_id, agent in list(self._open.items()):
            runs = by_task.get(task_id, [])
            if not is_cold(agent) and agent.get("runs", []) != runs:
                self._open[task_id] = agent = {**agent, "runs": runs}
                self._publish("task", {"id": task_id, "agent": agent, "settled": None})

    @staticmethod
    def _tied_runs(instance: str, dags: list, tied: set[str]) -> dict[str, list]:
        """The recent runs of the workflows of `instance` that an event ties: all the Ledger reads of its workflows."""
        return {
            f"{instance}/{dag['name']}": dag.get("recent", []) for dag in dags if f"{instance}/{dag['name']}" in tied
        }

    def _runnable(self) -> list[str]:
        """The `run_safe` workflows Run now is declared on: those their instance's adapter can start."""
        out = []
        for name in self._run_safe:
            instance, _, workflow = name.partition("/")
            startable = self._startable.get(instance)
            if startable is None or workflow in startable:
                out.append(name)
        return out

    def _workflows(self) -> list[dict]:
        """Every instance's workflows, each named `<instance>/<workflow>`; a pushed one an adapter lists, by its bare name
        or as the `<instance>/<workflow>` an ingested one is named, is drawn by that adapter."""
        adapters = [(i, dag["name"]) for i, dags in self._dags.items() if i != PUSHED_INSTANCE for dag in dags]
        listed = {name for _, name in adapters} | {f"{i}/{name}" for i, name in adapters}
        return [
            {**{key: value for key, value in dag.items() if key != "recent"}, "name": f"{instance}/{dag['name']}"}
            | ({"pool": f"{instance}/{dag['pool']}"} if dag.get("pool") else {})
            | _failed(dag)
            for instance, dags in self._dags.items()
            for dag in dags
            if instance != PUSHED_INSTANCE or dag["name"] not in listed
        ]
