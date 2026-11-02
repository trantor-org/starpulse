"""What StarPulse draws, held in memory and kept current by the adapters.

The board adapter (`starpulse.board.model.seam`) places each Board task here, the server keeps each task's latest state,
and every connected page gets one snapshot and then a delta per change. A restart resends only `snapshot` (`FEED_EVENT_RESEND`);
replayed deltas stay off the stream because that snapshot already carries their result. Each other machine's tasks arrive from
the event log (`machine_tasks`), and each runs adapter instance's workflows from its adapter module.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from starpulse.board import criteria
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.contracts.adapters import TaskKeys
from starpulse.event_log import lane_events, rating_events
from starpulse.machine_engine.model.snapshot import qualifier
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.stays import LaneRow
from starpulse.machine_engine.model.transitions import DEFAULT_STATUSES, board_machine

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog
    from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.board.feed.claims import ClaimMethods
from starpulse.board.feed.follow import Followed, InstanceRuns, Resumable, follow, retained
from starpulse.board.feed.ledgers import LedgerMethods
from starpulse.board.feed.lifecycle import LifecycleMixin
from starpulse.board.feed.reads import ReadMethods
from starpulse.board.feed.records import RecordsMixin
from starpulse.board.feed.runs import RunMethods
from starpulse.board.feed.shared import (
    _SENT_LOG,
    FEED_EVENT_RESEND,
    PUSHED_INSTANCE,
    SAVE_INTERVAL,
    BoardStore,
    CriteriaStore,
    ExpiriesStore,
    LaneRecorder,
    TaskIndex,
    entry_position,
    logger,
    read_model_lane_moves,
)
from starpulse.board.feed.views import ViewMethods

__all__ = [
    "BoardFeed",
    "BoardStore",
    "CriteriaStore",
    "ExpiriesStore",
    "FEED_EVENT_RESEND",
    "Followed",
    "InstanceRuns",
    "LaneRecorder",
    "PUSHED_INSTANCE",
    "Resumable",
    "SAVE_INTERVAL",
    "_SENT_LOG",
    "entry_position",
    "follow",
    "logger",
    "retained",
]


class BoardFeed(LifecycleMixin, RecordsMixin, ClaimMethods, ReadMethods, RunMethods, LedgerMethods, ViewMethods):
    """Each task's latest projected state, as the page's Board snapshot and the deltas after it.

    Entries arrive on the consumers' threads and pages read from request threads; one lock holds
    them apart, and a subscriber takes its snapshot and its queue under that lock so no change
    falls between the two. A machine's task whose latest move is older than `window_s` seconds
    (None: never) is left out of a snapshot. `board_url` is the tracker's address the page links tasks
    to (None: no links). `machines` are the machines the page draws, the Board's as `board` (None: a Board of
    Backlog.md's default statuses alone), and `cues` the board adapter's workflow cues. `domains` and `run_safe`
    are the config's, each workflow as `<instance>/<workflow>`. `source` names what the Board is read from, for the
    page to show until the board adapter has read it. `commit` is each runs instance's `[runs.commit]` keys, by instance
    name: they say which run parameters carry a merge's commit or a task, so the Ledger pairs a run with it for certain.

    Each open task carries `workable` and `workable_since`. A task is workable unless a dependency is not done (completed,
    or in the `done` lane) or it waits on Start Criteria that are not all met; it is then workable since the latest of
    when it entered its lane, when each dependency was done and when `evaluate_criteria` first saw its criteria all met.
    A task that is not workable has `workable_since` None.
    """

    def __init__(
        self,
        window_s: float | None = None,
        keys: TaskKeys | None = None,
        board_url: str | None = None,
        machines: Mapping[str, dict] | None = None,
        domains: Mapping[str, Sequence[str]] | None = None,
        run_safe: Collection[str] = (),
        cues: Sequence[dict] = (),
        source: str = "the board",
        capabilities: Mapping[str, bool] | None = None,
        hint: str | None = None,
        commit: Mapping[str, CommitKeys] | None = None,
        processes: Mapping[str, Sequence[tuple[str, Sequence[str]]]] | None = None,
        clock: Callable[[], float] = time.time,
        roles: StateRoles | None = None,
        read_model: ReadModel | None = None,
        standing: Callable[[str, str], Mapping[str, Any] | None] = lambda *_: None,
    ) -> None:
        self._hint = hint
        #: Set by `stop`: every thread an adapter runs for this feed (`spawn`) waits on it.
        self.stopped = threading.Event()
        self._threads: list[threading.Thread] = []
        #: When set, the Board's Tasks are read from it on each request and `_open` stays empty (D3: the feed holds no board).
        self._read_model = read_model
        #: The read model's position the page's deltas have been published up to; the snapshot carries what came before.
        self._followed = read_model.position() if read_model is not None else 0
        #: Which of the Board's States play which part (`Board.roles`); the default is Backlog.md's default statuses.
        self._roles = roles or StateRoles.of_statuses(DEFAULT_STATUSES)
        self._clock = clock
        #: A task's lane changes as the history keeps them (`History.lane_path`), read while the feed replays.
        self._lane_path: Callable[[str], list[dict]] = lambda _task: []
        #: Where a lane change the feed applies is kept (`HistoryStore`); None records nothing.
        self._lanes: LaneRecorder | None = None
        #: Where each lane change `_lanes` wrote is also appended as a `lane_events` entry; None appends nothing.
        self._lane_log: EventLog | None = None
        #: The pass/fail ratings the `task:ratings` stream holds, shown in the snapshot; None shows none.
        self._ratings: rating_events.Ratings | None = None
        #: The tasks an accepted take-over flipped to interactive, shown in the snapshot.
        self._interactive: set[str] = set()
        self._live_lanes = True
        #: Each task placed or retracted is also kept in `_search`; None keeps none.
        self._search: TaskIndex | None = None
        self._capabilities = {"edit": False, "archive": False, "create": False} | dict(capabilities or {})
        self._keys = keys
        self._domains = domains or {}
        self._processes = processes or {}
        self._run_safe = run_safe
        self._cues = cues
        self._source = source
        self._drawn = machines if machines is not None else {"board": board_machine(DEFAULT_STATUSES)}
        #: The Board machine's moves by source lane, which a read-model agent offers; a task's done lane offers none.
        self._lane_moves = read_model_lane_moves(self._drawn["board"]) if read_model is not None else {}
        #: The update the board's rules make to a task's move to a lane, which a read-model agent's moves carry.
        self._standing = standing
        #: The settled states a task's settling is recorded as a move into: archived always, completed where the Board
        #: has that state (a board whose last status is its final one settles there already).
        self._settle_lanes = {lane_events.ARCHIVED} | (
            {lane_events.COMPLETED} & {state["id"] for state in self._drawn["board"]["states"]}
        )
        self._board_url = board_url
        self._commit = commit or {}
        self._ties = self._tied_to_events(cues)
        qualify = qualifier(self._domains)
        #: How a failure of each workflow a machine event cues resolves, by `(event, workflow)`; any other resolves on its next success.
        self._resolves = {
            (cue["event"], qualify(cue["dag"])): cue["resolves"] for cue in cues if "event" in cue and "resolves" in cue
        }
        #: The Ledger as last published, so a change to it is sent once.
        self._ledgers: dict[str, list[dict]] = {}
        self._strip: dict | None = None
        self._pins: list[dict] = []
        self._lock = threading.RLock()
        #: Held by `put` from placing a change to recording its lane, by `save` while it copies the Board, and by a
        #: server write from the board's write to the record of its lane (`writes._record_written`), so a write's actor
        #: is recorded before the placement of its change is and a saved Board never holds a placed but unrecorded
        #: change. Taken before `_lock`.
        self.recording = threading.RLock()
        #: Counts every publish, suppressed or not: a snapshot held at this number is out of date once it moves.
        self._rev = 0
        #: Counts the publishes put on subscribers' queues.
        self._sent = 0
        #: The last publishes put on subscribers' queues, each with its count, so a page handed an older snapshot is told
        #: the changes that snapshot lacks.
        self._sent_log: deque[tuple[int, str, dict]] = deque(maxlen=_SENT_LOG)
        #: Set by every publish, for whoever rebuilds a held snapshot on change.
        self.revised = threading.Event()
        #: Held for a whole Ledger build, which runs outside `_lock`, so builds never overlap; taken before `_lock`, never under it.
        self._building = threading.Lock()
        self._window_s = window_s
        self._open: dict[str, dict] = {}
        self._settled: dict[str, dict] = {}
        #: Every placed task's assignee, a settled one's included, so a machine still drawing it keeps its colour.
        self._assignees: dict[str, str] = {}
        #: The pull request links every placed task cites, a settled one's included: its dependents read them for the
        #: pin bump that applies each (`cited`).
        self._cited: dict[str, list[str]] = {}
        #: The `titled` entry of every cold done task, whose stub in `_open` holds no title or labels.
        self._cold_titled: dict[str, dict] = {}
        self._dags: dict[str, list] = {}
        self._pools: dict[str, list] = {}
        #: Each instance's latest CPU reading (a `Cpu` as a dict); an instance that never reported one is absent.
        self._cpu: dict[str, dict] = {}
        #: The workflows each instance's adapter reported it can start; an instance not here can start all it has.
        self._startable: dict[str, frozenset[str]] = {}
        self._runs_errors: dict[str, str] = {}
        self._pulls: dict[str, list[dict]] = {}
        #: What the pull request projection kept (`PullRequests.answers`), saved so a restart reads warm.
        self._pull_answers: dict = {}
        self._pulls_unsaved = False
        #: Each task's latest refused claim (a board adapter's `refuse_claim` call): its reason and when the writer refused it.
        self._claims: dict[str, dict] = {}
        #: Each held working task's claim expiry from the claim-TTL sweep's latest pass, served as `claim_expires_at`.
        self._expiries: dict[str, float] = {}
        #: The Waiting tasks whose description declares Start Criteria, and for each task the open tasks that list it as a dependency.
        self._gated: set[str] = set()
        self._dependents: dict[str, set[str]] = {}
        #: When each gated task's criteria were first seen all met, kept while they stay met; a task not here has unmet criteria.
        self._met: dict[str, float] = {}
        self._evaluate: Callable[[str, str], list[dict]] = criteria.unevaluated
        self._criteria_store: CriteriaStore | None = None
        self._subscribers: list[queue.Queue] = []
        #: The queues of the pages streaming `/api/events` (a subset of `_subscribers`), which `announce` reaches.
        self._streams: list[queue.Queue] = []
        #: The pages with a Ledger open: the event each watches and the queue of that event's changed rows.
        self._watchers: list[tuple[str, queue.Queue]] = []
        self._awaiting = False  # pragma: no mutate — None is falsy too
        #: True from the machine events stream's start until its replay has placed every task.
        self._machines_reading = False
        self._expected: int | None = None
        self._seen = 0
        self._saved = 0
        self._store: tuple[BoardStore, str] | None = None
        #: What the board adapter keeps of its own beside the Board, saved and resumed with it (`keep_source`).
        self._kept: dict = {}
        self._kept_saved = self._kept
        self._lane_rows: Callable[..., list[LaneRow]] | None = None
        #: Set once the stream has been read up to the last entry it held when the feed started.
        self.ready = threading.Event()
        #: The whole Ledger as last built, which every page request reads (`_refresh_ledgers`); with no pull, run or
        #: lane history yet it holds only the empty events, so its window does not matter.
        self._ledger_full = self._ledger({}, {}, 0.0)
