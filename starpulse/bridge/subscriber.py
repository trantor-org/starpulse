"""Follows the log to keep each session's subscription on the task it holds.

Any move of a task, and any claim that lands (which writes no lane entry when the task is already in the working lane,
such as a new session adopting it, and names that session as the holder; a refused claim changes nothing), re-reads its holder from the board: every session that took subjects from the task and no longer holds
it drops them, and the holder gets the subjects its task kind's `claim` rule names, with the `pr_opened` subjects of
each pull request the task already cites. A pull request opening adds its `pr_opened` subjects to the holder, and a session dispatched to a task no other session holds gets the `claim` subjects, since a dispatch to a task already in the working lane writes no lane entry (a lane move drops them if the dispatch is refused). A holder whose task is in the working lane and in an incident type's reach (`bridge.reach`) also holds `incident.<type>.>`, dropped when the task leaves the lane. A kind with no rules, or a rule with no subject, subscribes the session to nothing.
Both are idempotent, so the bridge replaying an entry after a restart changes nothing. A task in a finished lane has no
holder though its file keeps the assignee, so its move to one drops the session's subjects; `reconcile` does the same for
every task a session's subscription holds and the session no longer does, such as those an older release left (a task
the read model does not return, or shows open with no holder, is skipped, never read as unheld: a restart's read model may not have folded the claim, and a move drops a released holder), and grants
each holder the `claim` subjects now named, so a claim list that grew reaches a session that claimed before. The entry's own lane says the task finished: the
read model the holder is read from is projected on another tail and may not have folded the move yet, so a move into
an open lane the read model's row does not show yet drops no session: a lagging row would read the holder as gone. After each
lane move and each `reconcile`, `settle` takes the names of the sessions that still have a consumer, so the
registrations of the sessions that ended, and those an older release left, are removed.
"""

import threading
from collections.abc import Callable, Collection, Mapping
from typing import Any, Protocol

from starpulse.bridge.reach import Reach
from starpulse.bridge.subjects import CLAIMS, INCIDENT, LANES, MACHINE, pull_number, pull_of, token
from starpulse.bridge.subscriptions import EXPLICIT, Rules, Subscription, expand
from starpulse.event_log.event_log import Entry
from starpulse.machine_engine.model.transitions import ARCHIVED, COMPLETED, lane_id

FINISHED = frozenset({"done", COMPLETED, ARCHIVED})

OPENED = "PR_OPENED"

DISPATCHED = "SESSION_DISPATCHED"


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
        settle: Callable[[Collection[str]], None] | None = None,
        reach: Mapping[str, Reach] | None = None,
    ) -> None:
        self._board, self._rules, self._store, self._feed = board, rules, store, feed
        self._reach = reach or {}
        self._settle = settle
        self._lock = threading.Lock()

    def handle(self, entry: Entry) -> None:
        with self._lock:
            task = str(entry.fields.get("task") or "")
            if not task:
                return
            if entry.stream == CLAIMS and not entry.fields.get("session"):
                return  # a refused claim moves no holder
            if entry.stream in (LANES, CLAIMS):
                # a lane move's session is its writer, often the holder's local id rather than the assignee's URL
                claimant = str(entry.fields.get("session") or "") if entry.stream == CLAIMS else ""
                self._moved(task, str(entry.fields.get("lane") or ""), claimant)
                self._settled()
            elif entry.stream == MACHINE and entry.fields.get("event") == OPENED and (number := pull_number(entry)):
                holder, rules, _ = self._holder(self._feed().task(task, lean=True))
                self._grant(holder, task, expand(self._board, rules.pr_opened, task=task, pr=number))
            elif entry.stream == MACHINE and entry.fields.get("event") == DISPATCHED:
                self._dispatched(task, token((entry.fields.get("data") or {}).get("session") or ""))

    def change(self, session: str, subjects: list[str], add: bool) -> tuple[bool, list[str]]:
        """Add the explicit `subjects` to `session`'s subscription, or remove them; whether it changed, and its filters."""
        with self._lock:
            subscription = self._store.get(session)
            if add:
                changed = subscription.add(EXPLICIT, subjects)
            else:
                changed = any([subscription.remove(subject) for subject in subjects])
            if changed:
                self._store.put(session, subscription)
            return changed, subscription.filters

    def _holder(self, agent: dict[str, Any] | None) -> tuple[str, Rules, list[str]]:
        """The session holding the task the read model's row `agent` shows (empty when there is no open row or it has no
        holder), its kind's rules, and the subjects of the incident types whose reach the task is in: a working task
        matching a type's kinds and areas."""
        if not agent or agent.get("state") in FINISHED:
            return "", Rules(), []
        kinds = [label.removeprefix("kind-") for label in agent.get("labels", ()) if label.startswith("kind-")]
        working = self._feed().roles.working if self._reach else ""
        incidents = [f"{INCIDENT}{kind}.>" for kind, reach in self._reach.items() if reach.covers(agent, working)]
        return token(agent.get("assignee") or ""), self._rules.get(next(iter(kinds), ""), Rules()), incidents

    def reconcile(self) -> None:
        """Drop each task's subjects from every session that does not hold the task now (an open task showing no holder is left, as the claim may not be folded), and give each holder the
        `claim` subjects its kind names now, so a claim list that grew since the session claimed reaches it; a holder
        whose task only another session held gets them too."""
        with self._lock:
            sessions = self._store.sessions()
            unheld: dict[str, tuple[str, list[str], list[str]]] = {}
            for session, subscription in sessions.items():
                changed = False
                for origin in [origin for origin in subscription.origins if origin != EXPLICIT]:
                    if (row := self._feed().task(origin, lean=True)) is None:
                        continue
                    holder, rules, incidents = self._holder(row)
                    if not holder and row.get("state") not in FINISHED:
                        continue  # may not have folded the claim: a move drops it, never a restart
                    if holder != session:
                        if holder and origin not in unheld and origin not in sessions.get(holder, Subscription()).origins:
                            unheld[origin] = (holder, self._held(origin, rules), incidents)
                        changed |= subscription.drop(origin)
                    else:
                        changed |= subscription.add(origin, self._held(origin, rules))
                        changed |= subscription.replace_prefixed(origin, INCIDENT, incidents)
                if changed:
                    self._store.put(session, subscription)
            for origin, (holder, subjects, incidents) in unheld.items():
                self._grant(holder, origin, subjects, incidents)
            self._settled()

    def _settled(self) -> None:
        if self._settle:
            self._settle(self._store.sessions())

    def _moved(self, task: str, lane: str, claimant: str) -> None:
        """`claimant` is a landed claim's session: the holder, though the read model may not have folded the claim. A
        lane move whose lane the read model's open row does not show yet drops no session, so a lagging row never
        drops the holder."""
        row = None if lane in FINISHED else self._feed().task(task, lean=True)
        holder, rules, incidents = self._holder(row)
        holder = token(claimant) if claimant else holder
        state = lane_id(str((row or {}).get("state") or ""))
        behind = bool(lane) and lane not in FINISHED and (row is None or bool(state) and state != lane_id(lane))
        held = [] if behind else self._store.holding(token(task))
        dropping = [session for session in held if session != holder]
        for session in dropping:
            subscription = self._store.get(session)
            subscription.drop(token(task))
            self._store.put(session, subscription)
        self._grant(holder, task, self._held(task, rules) if holder else [], incidents)

    def _dispatched(self, task: str, session: str) -> None:
        """A session dispatched to a task adopts it, and one already in the working lane, as at the scheduler's start, gets no
        lane entry, so this is the only entry that reaches its holder. The read model's lane may lag, so the lane is not
        checked: a refused dispatch leaves a task out of the working lane, and its next move drops the session. One
        another session holds is left to that session."""
        holder, rules, _ = self._holder(self._feed().task(task, lean=True))
        if session and holder in ("", session):
            self._grant(session, task, self._held(task, rules))

    def _held(self, task: str, rules: Rules) -> list[str]:
        """The `claim` subjects, with the `pr_opened` subjects of each pull request the task already cites: a session
        claiming after the PR opened, or claiming again from Waiting, never saw its `PR_OPENED`."""
        subjects = expand(self._board, rules.claim, task=task)
        if rules.pr_opened:
            for pr in filter(None, map(pull_of, self._feed().cited(task))):
                subjects += expand(self._board, rules.pr_opened, task=task, pr=pr)
        return subjects

    def _grant(self, session: str, task: str, subjects: list[str], incidents: list[str] | None = None) -> None:
        """Add `subjects` to the session's subscription under `task`; with `incidents`, they are also the only incident
        subjects it holds there, so a task that left its types' reach stops receiving them."""
        if not session:
            return
        subscription = self._store.get(session)
        changed = subscription.add(token(task), subjects)
        if incidents is not None:
            changed |= subscription.replace_prefixed(token(task), INCIDENT, incidents)
        if changed:
            self._store.put(session, subscription)
