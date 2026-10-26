"""Feed criteria, expiries, pull requests and refused claims."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from starpulse.board import criteria

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.feed.shared import (
    CRITERIA_INTERVAL,
    CriteriaStore,
    ExpiriesStore,
    is_cold,
    logger,
)


class ClaimMethods:
    def track_criteria(self, evaluate: Callable[[str, str], list[dict]] | None, store: CriteriaStore | None) -> None:
        """Evaluate Waiting tasks' Start Criteria with `evaluate` (None: each is `not evaluated`, so none is met).

        `store` keeps when each task's criteria were first seen met, so a restart keeps how long a task has been
        workable; None keeps it in memory only.
        """
        with self._lock:
            self._evaluate = evaluate or criteria.unevaluated
            self._criteria_store = store
            if store is not None:
                try:
                    self._met = dict(store.criteria_met())
                except Exception as exc:  # the store is down; the next pass dates each task afresh
                    logger.warning("StarPulse: cannot read when Start Criteria were met: %s", exc)
            self._reassess(list(self._open))

    def evaluate_criteria(self) -> None:
        """Evaluate the Start Criteria of every Waiting task whose dependencies are done, and publish each task whose
        workability changed. A task whose criteria are all met keeps the moment it was first seen so; a task whose
        criteria are not met, or that is no longer evaluated, is forgotten, so its next met moment is a new one."""
        with self._lock:
            due = [(t, self._open[t]["description"]) for t in sorted(self._gated) if self._unblocked(self._open[t])]
            evaluate, now = self._evaluate, self._clock()
        met = []
        for task, description in due:
            try:
                results = evaluate(task, description)
            except Exception as exc:  # an evaluator is meant to return errors as results; this one raised
                logger.warning("StarPulse: cannot evaluate the Start Criteria of %s: %s", task, exc)
                continue
            if results and all(result["status"] == "met" for result in results):
                met.append(task)
        with self._lock:
            kept = {task: self._met.get(task, now) for task in met}
            if kept == self._met:
                return
            previous, self._met, store = self._met, kept, self._criteria_store
            self._reassess(previous.keys() | kept.keys())
        if store is not None:
            try:
                store.save_criteria_met(kept)
            except Exception as exc:  # the store is down; the pass stands and the next change saves it
                logger.warning("StarPulse: cannot save when Start Criteria were met: %s", exc)

    def keep_criteria(self, stop: threading.Event, interval: float = CRITERIA_INTERVAL) -> None:
        """Evaluate now and then every `interval` seconds until `stop` is set."""
        while True:
            self.evaluate_criteria()
            if stop.wait(interval):
                return

    def follow_criteria(self, store: CriteriaStore, stop: threading.Event, interval: float = CRITERIA_INTERVAL) -> None:
        """Adopt, every `interval` seconds until `stop` is set, when `store` says each task's Start Criteria were met,
        as the process that evaluates them keeps it there; this feed evaluates nothing. A store that cannot be read
        leaves what the feed held. The first pass assesses every open task, as `track_criteria` does."""
        first = True
        while True:
            try:
                met = dict(store.criteria_met())
            except Exception as exc:  # the store is down; the next pass reads it again
                logger.warning("StarPulse: cannot read when Start Criteria were met: %s", exc)
                met = None
            with self._lock:
                previous = self._met
                if met is not None:
                    self._met = met
                if first or self._met != previous:
                    self._reassess(list(self._open) if first else previous.keys() | self._met.keys())
            first = False
            if stop.wait(interval):
                return

    def follow_expiries(self, store: ExpiriesStore, stop: threading.Event, interval: float = CRITERIA_INTERVAL) -> None:
        """Adopt, every `interval` seconds until `stop` is set, the claim expiries the board worker's sweep saved, as
        `follow_criteria` adopts the dates. A store that cannot be read leaves what the feed held."""
        while True:
            try:
                self.serve_expiries(store.claim_expiries())
            except Exception as exc:  # the store is down; the next pass reads it again
                logger.warning("StarPulse: cannot read the claim expiries: %s", exc)
            if stop.wait(interval):
                return

    def pull_requests(self) -> dict[str, list[str]]:
        """Each open task's pull request links, for the tasks that cite any."""
        with self._lock:
            if self._read_model is not None:  # `_open` stays empty under the read model
                prs = {agent["id"]: agent["prs"] for agent in self._read_model_hot()}
            else:
                prs = {
                    task: agent["prs"] if not is_cold(agent) else self._cited.get(task)
                    for task, agent in self._open.items()
                }
            return {task: list(links) for task, links in prs.items() if links}

    def set_pulls(self, pulls: dict[str, list[dict]], answers: dict | None = None) -> None:
        """Take each task's pull request state and publish it when it differs from before; `answers` is what the
        projection kept, saved with the Board so a restart need not ask GitHub again."""
        with self._lock:
            if answers is not None and answers != self._pull_answers:
                self._pull_answers, self._pulls_unsaved = answers, True
            if pulls == self._pulls:
                return
            self._pulls_unsaved = True
            self._pulls = pulls
            self._publish("pulls", {"pulls": pulls})
        self._refresh_ledgers()

    def refuse_claim(self, task: str, reason: str, at: float, *, publish: bool = True) -> None:
        """Keep the board writer's latest refusal of an agent's claim on `task` and, unless `publish` is False, publish it."""
        with self._lock:
            self._claims[task] = {"reason": reason, "at": at}
            if publish:
                self._publish("claim", {"task": task, "reason": reason, "at": at})

    def serve_expiries(self, expiries: Mapping[str, float]) -> None:
        """Keep the claim-TTL sweep's latest pass: each held working task's claim expiry, and publish each open task whose changed."""
        with self._lock:
            changed = [
                task
                for task in self._expiries.keys() | expiries.keys()
                if self._expiries.get(task) != expiries.get(task)
            ]
            self._expiries = dict(expiries)
            for task_id in changed:
                if (agent := self._open.get(task_id)) is not None:
                    self._open[task_id] = self._expiring(agent)
                    self._publish("task", {"id": task_id, "agent": self._open[task_id], "settled": None})

    def _expiring(self, agent: dict) -> dict:
        """A copy of the agent with its task's claim expiry from the claim-TTL sweep's latest pass; no key when it has none."""
        expiry = self._expiries.get(agent["id"])
        if expiry is None and "claim_expires_at" not in agent:
            return dict(agent)
        return {**agent, "claim_expires_at": expiry}
