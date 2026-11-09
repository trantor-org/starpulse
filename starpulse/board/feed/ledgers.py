"""Feed ledgers: the lane and rating rows a page reads in pages."""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING

from starpulse.board.ledger import (
    MERGE_EVENT,
    NEXT,
    PAGE,
    STRIP_BUCKET,
    Occurrence,
    build,
    page,
    pull_occurrences,
    reruns,
    strip,
)
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.contracts.adapters import TaskKeys
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.feed.shared import (
    LEDGER_WINDOW,
)


class LedgerMethods:
    def _ledger(self, pulls: dict[str, list[dict]], recent: dict[str, list], since: float) -> dict[str, list[dict]]:
        """Every tied Board event's occurrences since `since`, newest first, with the run of every workflow tied to it
        among the `recent` runs (`starpulse.board.ledger`).

        The merge event's occurrences are the merged `pulls`; any other event's are the tasks that made one of its
        moves, a lane it leaves and the lane it reaches, read from the lane history `read_lanes` was given. A move
        into a lane the event reaches from another lane is not the event. Only the window's changes are read: this runs on
        every run, pull and live lane update, and the whole history is far larger than a day.
        """
        events: dict[str, list[Occurrence]] = {}
        if MERGE_EVENT in self._ties:
            events[MERGE_EVENT] = [o for o in pull_occurrences(pulls) if o.at >= since]
        moves = {
            event: {
                (t["source"], t["target"]) for t in self._drawn["board"].get("transitions", []) if t["event"] == event
            }
            for event in self._ties.keys() - {MERGE_EVENT}
        }
        if moves and self._lane_rows is not None:
            for task, at, old, to in self._lane_rows(since):
                for event, made in moves.items():
                    if old is not None and (lane_id(old), lane_id(to)) in made:
                        events.setdefault(event, []).append(Occurrence(f"{task}@{at}", at, (task,)))
        return build(
            events,
            self._ties,
            recent,
            lambda dag: self._commit.get(dag.partition("/")[0]),
            lambda event, dag: self._resolves.get((event, dag), NEXT),
        )

    def _recent_runs(self) -> dict[str, list]:
        return {
            f"{instance}/{dag['name']}": dag.get("recent", []) for instance, dags in self._dags.items() for dag in dags
        }

    @property
    def keys(self) -> TaskKeys | None:
        """The task keys the feed was built with, or None when it takes every key."""
        return self._keys

    def commit_keys(self, instance: str) -> CommitKeys | None:
        """The `[runs.commit]` of runs instance `instance`, or None when it declares none."""
        return self._commit.get(instance)

    def open_failure(self, dag: str) -> dict | None:
        """The newest unresolved failure of workflow `dag` (`<instance>/<workflow>`) as `{runId, params}`, the parameters
        that run started with, or None when it has none or the runs adapter no longer lists the run."""
        with self._lock:
            open_ = [
                fail
                for rows in self._ledger_full.values()
                for row in rows
                if (fail := row["fails"].get(dag)) and fail["resolved"] is None
            ]
            instance, _, workflow = dag.partition("/")
            recent = next((d.get("recent", []) for d in self._dags.get(instance, []) if d["name"] == workflow), [])
        newest = max(open_, key=lambda fail: fail["startedAt"], default=None)
        run = next((r for r in recent if newest and r["runId"] == newest["runId"]), None)
        return None if run is None else {"runId": run["runId"], "params": dict(run.get("params", {}))}

    def _head(self, ledgers: dict[str, list[dict]]) -> dict[str, list[dict]]:
        """`ledgers` with each event's rows cut to the newest page; older ones come from `ledger_rows`."""
        since = self._clock() - LEDGER_WINDOW
        return {event: page(rows, before=None, limit=PAGE, since=since)[0] for event, rows in ledgers.items()}

    def _merge_strip(self, ledgers: dict[str, list[dict]]) -> dict | None:
        """The 24-hour strip of the merge ledger (`ledger.strip`), counted over every row rather than the page sent;
        None when no workflow is tied to the merge event."""
        if MERGE_EVENT not in ledgers:
            return None
        recent = self._recent_runs()
        forced = [
            at
            for dag in self._ties[MERGE_EVENT]
            for at in reruns(recent.get(dag, ()), self._commit.get(dag.partition("/")[0]))
        ]
        return strip(ledgers[MERGE_EVENT], forced, now=self._clock(), span=LEDGER_WINDOW, bucket=STRIP_BUCKET)

    def _merge_pins(self, ledgers: dict[str, list[dict]], head: dict[str, list[dict]]) -> list[dict]:
        """The pinned merge rows of the last day that the newest page leaves out, so a failure waiting on its cue is
        never paged out of sight."""
        shown = {row["key"] for row in head.get(MERGE_EVENT, ())}
        return [row for row in ledgers.get(MERGE_EVENT, ()) if row["pinned"] and row["key"] not in shown]

    def _ledger_view(self, full: dict[str, list[dict]]) -> dict:
        head = self._head(full)
        return {"ledgers": head, "mergeStrip": self._merge_strip(full), "mergePins": self._merge_pins(full, head)}

    def _ledger_marks(self, full: dict[str, list[dict]]) -> dict:
        """What the snapshot carries of the Ledger: the merge strip and pins, which the starmap draws always; a
        Ledger's rows come when a page opens it."""
        view = self._ledger_view(full)
        return {"mergeStrip": view["mergeStrip"], "mergePins": view["mergePins"]}

    def ledger_rows(self, event: str, before: float | None, limit: int) -> dict | None:
        """`GET /api/ledger/<event>`: the next `limit` rows older than `before` (None: the newest), `{rows, more}`, none
        from beyond `LEDGER_WINDOW`; None when no workflow is tied to `event`."""
        with self._lock:
            return self._ledger_page(event, before, limit)

    def _ledger_page(self, event: str, before: float | None, limit: int) -> dict | None:
        if event not in self._ties:
            return None
        found, more = page(
            self._ledger_full.get(event, ()), before=before, limit=limit, since=self._clock() - LEDGER_WINDOW
        )
        return {"rows": found, "more": more}

    def watch_ledger(self, event: str) -> tuple[list[dict], bool, queue.Queue] | None:
        """A page opening `event`'s Ledger: its newest rows, whether older ones remain, and the queue of every change to
        those rows after them, `{rows}` each; None when no workflow is tied to `event`. Only this event's changes
        reach the queue, and no stream of `/api/events` carries a row."""
        with self._lock:
            if (found := self._ledger_page(event, None, PAGE)) is None:
                return None
            changes: queue.Queue = queue.Queue()
            self._watchers.append((event, changes))
            return found["rows"], found["more"], changes

    def unwatch_ledger(self, changes: queue.Queue) -> None:
        with self._lock:
            self._watchers = [(event, held) for event, held in self._watchers if held is not changes]
