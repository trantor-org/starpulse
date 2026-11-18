"""Feed claim expiries, pull requests and refused claims."""

import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING

from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.model.feed.shared import (
    CLAIM_EXPIRIES_STATE,
    DatesStore,
    ExpiriesStore,
    StateLog,
    is_cold,
    logger,
)


class ClaimMethods:
    def adopt_expiries(self, store: ExpiriesStore) -> None:
        """Adopt the claim expiries the board worker's sweep saved, as the claim sweep saved them. A store that
        cannot be read leaves what the feed held."""
        try:
            self.serve_expiries(store.claim_expiries())
        except Exception as exc:  # the store is down; the next change reads it again
            logger.warning("StarPulse: cannot read the claim expiries: %s", exc)

    def follow_dates(self, log: StateLog, store: DatesStore, stop: StopEvent) -> None:
        """Adopt the claim expiries now and each time the board worker saves them (`PushedDates`), until `stop` is set."""
        adopting = (
            threading.Lock()
        )  # a read and its apply finish before the next starts, so an old read never lands last

        def adopt_claims() -> None:
            with adopting:
                self.adopt_expiries(store)

        log.follow_state(CLAIM_EXPIRIES_STATE, adopt_claims, stop, thread_name="expiries-follow")
        adopt_claims()  # the follower is watching first, so a save between is not missed

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
                self.unsaved.set()
            if pulls == self._pulls:
                return
            self._pulls_unsaved = True
            self.unsaved.set()
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
        if self._read_model is None:
            return
        for task_id in changed:  # a read model holds no open task: its change is announced as the Task a build draws
            if (agent := self.drawn_task(task_id)[0]) is not None:
                with self._lock:
                    self._publish("task", {"id": task_id, "agent": agent, "settled": None})

    def _expiring(self, agent: dict) -> dict:
        """A copy of the agent with its task's claim expiry from the claim-TTL sweep's latest pass; no key when it has none."""
        expiry = self._expiries.get(agent["id"])
        if expiry is None:
            return {key: value for key, value in agent.items() if key != "claim_expires_at"}
        return {**agent, "claim_expires_at": expiry}
