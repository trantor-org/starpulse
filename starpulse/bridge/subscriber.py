"""Follows the log to keep each session's subscription on the task it holds.

Any move of a task, and any claim that lands (which writes no lane entry when the task is already in the working lane,
such as a new session adopting it), re-reads its holder from the board: every session that took subjects from the task and no longer holds
it drops them, and the holder gets the subjects its task kind's `claim` rule names, with the `pr_opened` subjects of
each pull request the task already cites. A pull request opening adds its `pr_opened` subjects to the holder. A kind with no rules, or a rule with no subject, subscribes the session to nothing.
Both are idempotent, so the bridge replaying an entry after a restart changes nothing. A task in a finished lane has no
holder though its file keeps the assignee, so its move to one drops the session's subjects; `reconcile` does the same for
every task a session's subscription holds and the session no longer does, such as those an older release left, and grants
each holder the `claim` subjects now named, so a claim list that grew reaches a session that claimed before. That drop
deletes the session's consumer before the delivery route can read the move, so a move into a finished lane `end_lanes`
names runs `end` here, before the drop so a retried entry runs it again, whether or not a consumer held the task: a
session whose consumer was lost (a restart's `reconcile` read a holder the read model had not folded yet) is still
bound to the task, and `end` is scoped to the task and idempotent. The entry's own lane says the task finished: the
read model the holder is read from is projected on another tail and may not have folded the move yet.
"""

from collections.abc import Callable, Collection, Mapping
from typing import Any, Protocol

from starpulse.bridge.subjects import CLAIMS, LANES, MACHINE, pull_number, pull_of, token
from starpulse.bridge.subscriptions import EXPLICIT, Rules, Subscription, expand
from starpulse.event_log.event_log import Entry
from starpulse.event_log.lane_events import ARCHIVED, COMPLETED

FINISHED = frozenset({"done", COMPLETED, ARCHIVED})

OPENED = "PR_OPENED"


class Store(Protocol):
    def get(self, session: str) -> Subscription: ...

    def put(self, session: str, subscription: Subscription) -> None: ...

    def holding(self, origin: str) -> list[str]: ...

    def sessions(self) -> dict[str, Subscription]: ...


class Subscriber:
    def __init__(
        self,
        board: str,
        rules: Mapping[str, Rules],
        store: Store,
        feed: Callable[[], Any],
        end: Callable[[str], None] | None = None,
        end_lanes: Collection[str] = (),
    ) -> None:
        self._board, self._rules, self._store, self._feed = board, rules, store, feed
        self._end, self._end_lanes = end, end_lanes

    def handle(self, entry: Entry) -> None:
        task = str(entry.fields.get("task") or "")
        if not task:
            return
        if entry.stream in (LANES, CLAIMS):
            self._moved(task, str(entry.fields.get("lane") or ""))
        elif entry.stream == MACHINE and entry.fields.get("event") == OPENED and (number := pull_number(entry)):
            holder, rules = self._holder(task)
            self._grant(holder, task, expand(self._board, rules.pr_opened, task=task, pr=number))

    def _holder(self, task: str) -> tuple[str, Rules]:
        """The session holding `task` (empty when the board has no open task or it has no holder) and its kind's rules."""
        agent = self._feed().task(task, lean=True)
        if not agent or agent.get("state") in FINISHED:
            return "", Rules()
        kinds = [label.removeprefix("kind-") for label in agent.get("labels", ()) if label.startswith("kind-")]
        return token(agent.get("assignee") or ""), self._rules.get(next(iter(kinds), ""), Rules())

    def reconcile(self) -> None:
        """Drop each task's subjects from every session that does not hold the task now, and give each holder the
        `claim` subjects its kind names now, so a claim list that grew since the session claimed reaches it."""
        for session, subscription in self._store.sessions().items():
            changed = False
            for origin in [origin for origin in subscription.origins if origin != EXPLICIT]:
                holder, rules = self._holder(origin)
                if holder != session:
                    changed |= subscription.drop(origin)
                else:
                    changed |= subscription.add(origin, self._held(origin, rules))
            if changed:
                self._store.put(session, subscription)

    def _moved(self, task: str, lane: str) -> None:
        holder, rules = ("", Rules()) if lane in FINISHED else self._holder(task)
        dropping = [session for session in self._store.holding(token(task)) if session != holder]
        if self._end and lane in FINISHED and lane in self._end_lanes:
            self._end(task)
        for session in dropping:
            subscription = self._store.get(session)
            subscription.drop(token(task))
            self._store.put(session, subscription)
        self._grant(holder, task, self._held(task, rules) if holder else [])

    def _held(self, task: str, rules: Rules) -> list[str]:
        """The `claim` subjects, with the `pr_opened` subjects of each pull request the task already cites: a session
        claiming after the PR opened, or claiming again from Waiting, never saw its `PR_OPENED`."""
        subjects = expand(self._board, rules.claim, task=task)
        if rules.pr_opened:
            for pr in filter(None, map(pull_of, self._feed().cited(task))):
                subjects += expand(self._board, rules.pr_opened, task=task, pr=pr)
        return subjects

    def _grant(self, session: str, task: str, subjects: list[str]) -> None:
        if not session:
            return
        subscription = self._store.get(session)
        if subscription.add(token(task), subjects):
            self._store.put(session, subscription)
