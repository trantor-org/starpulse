"""Follows the log to keep each session's subscription on the task it holds.

Any move of a task re-reads its holder from the board: every session that took subjects from the task and no longer holds
it drops them, and the holder gets the subjects its task kind's `claim` rule names. A pull request opening adds the
`pr_opened` subjects to the holder. A kind with no rules, or a rule with no subject, subscribes the session to nothing.
Both are idempotent, so the bridge replaying an entry after a restart changes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from starpulse.bridge.subjects import LANES, MACHINE, pull_number, token
from starpulse.bridge.subscriptions import Rules, Subscription, expand
from starpulse.event_log.event_log import Entry

OPENED = "PR_OPENED"


class Store(Protocol):
    def get(self, session: str) -> Subscription: ...

    def put(self, session: str, subscription: Subscription) -> None: ...

    def holding(self, origin: str) -> list[str]: ...


class Subscriber:
    def __init__(self, board: str, rules: Mapping[str, Rules], store: Store, feed: Callable[[], Any]) -> None:
        self._board, self._rules, self._store, self._feed = board, rules, store, feed

    def handle(self, entry: Entry) -> None:
        task = str(entry.fields.get("task") or "")
        if not task:
            return
        if entry.stream == LANES:
            self._moved(task)
        elif entry.stream == MACHINE and entry.fields.get("event") == OPENED and (number := pull_number(entry)):
            holder, rules = self._holder(task)
            self._grant(holder, task, expand(self._board, rules.pr_opened, task=task, pr=number))

    def _holder(self, task: str) -> tuple[str, Rules]:
        """The session holding `task` (empty when the board has no open task or it has no holder) and its kind's rules."""
        agent = self._feed().task(task, lean=True)
        if not agent:
            return "", Rules()
        kinds = [label.removeprefix("kind-") for label in agent.get("labels", ()) if label.startswith("kind-")]
        return token(agent.get("assignee") or ""), self._rules.get(next(iter(kinds), ""), Rules())

    def _moved(self, task: str) -> None:
        holder, rules = self._holder(task)
        for session in self._store.holding(token(task)):
            if session != holder:
                subscription = self._store.get(session)
                subscription.drop(token(task))
                self._store.put(session, subscription)
        self._grant(holder, task, expand(self._board, rules.claim, task=task))

    def _grant(self, session: str, task: str, subjects: list[str]) -> None:
        if not session:
            return
        subscription = self._store.get(session)
        if subscription.add(token(task), subjects):
            self._store.put(session, subscription)
