"""What StarPulse draws: the Board's tasks come from the read model, the other machines' tasks from the event log.

Each connected page gets one snapshot and then a delta per change. A restart resends only `snapshot` (`FEED_EVENT_RESEND`);
replayed deltas stay off the stream because that snapshot already carries their result. Each other machine's tasks arrive from
the event log (`machine_tasks`), and each runs adapter instance's workflows from its adapter module.
"""

import queue
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from typing import TYPE_CHECKING, Any

from starpulse.board.model.commit_keys import CommitKeys
from starpulse.contracts.adapters import TaskKeys
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.snapshot import qualifier
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.stays import LaneRow
from starpulse.machine_engine.model.transitions import DEFAULT_STATUSES, board_machine

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog
    from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.board.model.feed.pulls import PullMethods
from starpulse.board.model.feed.follow import Followed, InstanceRuns, Resumable, follow, retained
from starpulse.board.model.feed.ledgers import LedgerMethods
from starpulse.board.model.feed.lifecycle import LifecycleMixin
from starpulse.board.model.feed.reads import ReadMethods
from starpulse.board.model.feed.records import RecordsMixin
from starpulse.board.model.feed.runs import RunMethods
from starpulse.board.model.feed.shared import (
    FEED_EVENT_RESEND,
    PUSHED_INSTANCE,
    SAVE_DEBOUNCE,
    BoardStore,
    LaneRecorder,
    entry_position,
    logger,
    read_model_lane_moves,
)
from starpulse.board.model.feed.views import ViewMethods

__all__ = [
    "BoardFeed",
    "BoardStore",
    "FEED_EVENT_RESEND",
    "Followed",
    "InstanceRuns",
    "LaneRecorder",
    "PUSHED_INSTANCE",
    "Resumable",
    "SAVE_DEBOUNCE",
    "entry_position",
    "follow",
    "logger",
    "retained",
]


class BoardFeed(LifecycleMixin, RecordsMixin, PullMethods, ReadMethods, RunMethods, LedgerMethods, ViewMethods):
    """Each task's latest projected state, as the page's Board snapshot and the deltas after it.

    Entries arrive on the consumers' threads and pages read from request threads; one lock holds
    them apart, and a subscriber takes its snapshot and its queue under that lock so no change
    falls between the two. A machine's task whose latest move is older than `window_s` seconds
    (None: never) is left out of a snapshot. `machines` are the machines the page draws, the Board's as `board` (None: a Board of
    Backlog.md's default statuses alone), and `cues` the board adapter's workflow cues. `domains`
    is the config's, each workflow as `<instance>/<workflow>`. `source` names what the Board is read from, for the
    page to show until the board adapter has read it. `commit` is each runs instance's `[runs.commit]` keys, by instance
    name: they say which run parameters carry a merge's commit or a task, so the Ledger pairs a run with it for certain. `change_url` turns a task link's reference into the page of its pull request. `start_urls` is each instance's runner start page, by instance name: each of its jobs carries it.
    """

    def __init__(
        self,
        read_model: ReadModel,
        window_s: float | None = None,
        keys: TaskKeys | None = None,
        machines: Mapping[str, dict] | None = None,
        domains: Mapping[str, Sequence[str]] | None = None,
        cues: Sequence[dict] = (),
        source: str = "the board",
        commit: Mapping[str, CommitKeys] | None = None,
        start_urls: Mapping[str, str] | None = None,
        processes: Mapping[str, Sequence[tuple[str, Sequence[str]]]] | None = None,
        clock: Callable[[], float] = time.time,
        roles: StateRoles | None = None,
        standing: Callable[[str, str], Mapping[str, Any] | None] = lambda *_: None,
        readable: Callable[[Mapping[str, Any], str], str] = lambda *_: "",
        default_profiles: Mapping[str, Mapping[str, str]] | None = None,
        activity: Callable[[str], dict[str, Any]] = lambda _: {"state": "unknown"},
        change_url: Callable[[str], str | None] = lambda _: None,
    ) -> None:
        #: Set by `stop`: every thread an adapter runs for this feed (`spawn`) waits on it.
        self.stopped = StopEvent()
        #: The sweeper's board passes by kind name, each registered by the adapter that keeps the deadlines it re-reads:
        #: a call returns (sampled, corrected).
        self.reconcilers: dict[str, Callable[[], tuple[int, int]]] = {}
        self._threads: list[threading.Thread] = []
        #: Where the Board's Tasks are read from, on each request: the feed holds no board.
        self._read_model = read_model
        #: The `open_tasks` list this thread's `one_read` built, None outside one.
        self._pinned = threading.local()
        #: The `(read model position, rows by key)` this thread's `pinned_rows` holds, None outside one.
        self._rows = threading.local()
        #: The list `open_tasks` last built, with the read model position and local day it was built at: a call that finds
        #: both unchanged answers from it, since no task row differs.
        self._built: tuple[tuple[int, float], list[dict]] | None = None
        self._build_lock = threading.Lock()
        #: The read model's position the page's deltas have been published up to; the snapshot carries what came before.
        self._followed = read_model.position()
        #: Which of the Board's States play which part (`Board.roles`); the default is Backlog.md's default statuses.
        self._roles = roles or StateRoles.of_statuses(DEFAULT_STATUSES)
        self._clock = clock
        #: The profile a Task with none of its own draws, by its `kind-*` then `size-*` label (`[board.default_profiles]`).
        self._default_profiles = default_profiles or {}
        #: Where a lane change the feed applies is kept (`HistoryStore`); None records nothing.
        self._lanes: LaneRecorder | None = None
        #: Where each lane change `_lanes` wrote is also appended as a `lane_events` entry; None appends nothing.
        self._lane_log: EventLog | None = None
        #: The tasks an accepted take-over flipped to interactive, shown in the snapshot.
        self._interactive: set[str] = set()
        self._keys = keys
        self._domains = domains or {}
        self._processes = processes or {}
        self._cues = cues
        self._source = source
        self._drawn = machines if machines is not None else {"board": board_machine(DEFAULT_STATUSES)}
        #: The Board machine's moves by source lane, which a read-model agent offers; a task's done lane offers none.
        self._lane_moves = read_model_lane_moves(self._drawn["board"])
        #: The update the board's rules make to a task's move to a lane, which a read-model agent's moves carry.
        self._standing = standing
        #: What the board's `readable` rules find broken in a task's description, which a read-model agent carries.
        self._readable = readable
        #: The session activity of a held working task's holder, which its agent carries; `unknown` when no running session holds it.
        self._activity = activity
        #: The page of the change a stored link's reference names (None: no forge owns it), which a task's `prs` carry.
        self._change_url = change_url
        self._commit = commit or {}
        self._start_urls = start_urls or {}
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
        #: Each task's `recording_of`, made on first use.
        self._recording_of: dict[str, threading.RLock] = {}
        #: Set by every publish, for whoever rebuilds a held snapshot on change.
        self.revised = threading.Event()
        #: Held for a whole Ledger build, which runs outside `_lock`, so builds never overlap; taken before `_lock`, never under it.
        self._building = threading.Lock()
        #: Where a Ledger rebuild runs when not on the thread that applied the update (`build_ledgers_on`), and whether one waits there.
        self._ledger_worker: Executor | None = None
        self._ledger_queued = threading.Event()
        self._window_s = window_s
        #: How far back the snapshot's machine lanes read when no `window_s` narrows them (an open Task's lane stays); None: no cap.
        self._lane_cap_s: float | None = None
        #: Each key a task was known by before, to the key it holds now.
        self._aliases: dict[str, str] = {}
        self._dags: dict[str, list] = {}
        self._pools: dict[str, list] = {}
        self._runs_errors: dict[str, str] = {}
        self._pulls: dict[str, list[dict]] = {}
        #: What `relinked` tells after a task's link is written or removed (`on_relinked`).
        self._relink_listeners: list[Callable[[str], None]] = []
        #: What the pull request projection kept (`PullRequests.answers`), saved so a restart reads warm.
        self._pull_answers: dict = {}
        self._subscribers: list[queue.Queue] = []
        #: The pages with a Ledger open: the event each watches and the queue of that event's changed rows.
        self._watchers: list[tuple[str, queue.Queue]] = []
        self._awaiting = False
        self._expected: int | None = None
        self._seen = 0
        self._lane_rows: Callable[..., list[LaneRow]] | None = None
        #: Set once the stream has been read up to the last entry it held when the feed started.
        self.ready = threading.Event()
        #: The whole Ledger as last built, which every page request reads (`_refresh_ledgers`); with no pull, run or
        #: lane history yet it holds only the empty events, so its window does not matter.
        self._ledger_full = self._ledger({}, {}, 0.0)
