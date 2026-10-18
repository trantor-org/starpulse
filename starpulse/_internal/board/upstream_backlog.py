"""The upstream Backlog.md adapter: a project's task files in, the board contract out.

Upstream Backlog.md (MrLesk/Backlog.md) has no projection stream and no server to ask; its state is
the Markdown files under the project's `backlog/` directory. `UpstreamBacklog` polls them, hands each
changed file to a feed as a `BoardTask`, and the Board machine comes from the project's own statuses
(`backlog/config.yml`), so a lane is a status the project configured. It has no network transport or projection
dependency, so it runs from the files alone. It is the `[board] type = "upstream_backlog"` adapter.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import logging
import re
import shlex
import subprocess
import threading
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml

try:  # libyaml's loader: the same safe schema and errors, a tenth of the pure-Python parse time over a whole board
    from yaml import CSafeLoader as _FrontmatterLoader
except ImportError:
    from yaml import SafeLoader as _FrontmatterLoader

from starpulse._internal.board import project_machines
from starpulse._internal.board.dir_watch import DirWatch
from starpulse._internal.board.seam import Board, MoveWriter, Written
from starpulse._internal.machines.transitions import DEFAULT_STATUSES, board_machine, lane_id
from starpulse.contracts.task_keys import TaskKeys

if TYPE_CHECKING:
    from starpulse._internal.eventlog.event_log import EventLog
    from starpulse._internal.feed.board_feed import BoardFeed
    from starpulse._internal.machines.machine_definition import Compiled, Writer
    from starpulse._internal.machines.snapshot import Qualify
    from starpulse.contracts.adapters import BoardTask, Move

logger = logging.getLogger(__name__)

#: The modules whose code turns a task file into what the feed saves: changing any of them, like changing the project's
#: config or machine, starts the next run from a full scan rather than from the Board an older one saved.
_PROJECTION = (__name__, "starpulse._internal.feed.board_feed", "starpulse.contracts.adapters")

DEFAULT_PREFIX = "task"
#: Seconds between scans where no file watch can run.
_POLL = 2.0
#: Seconds between the full scans that back the file watch up, unless the board sets `interval`.
BACKSTOP = 60.0
#: Where a task file sits decides whether it is in a lane or has left them; subtasks are ids like `task-1.1`.
_FOLDERS: tuple[tuple[str, Literal["completed", "archived"] | None], ...] = (
    ("tasks", None),
    ("completed", "completed"),
    ("archive/tasks", "archived"),
)
_DONE_LANE = "done"
_DESCRIPTION = re.compile(r"<!-- SECTION:DESCRIPTION:BEGIN -->(.*?)<!-- SECTION:DESCRIPTION:END -->", re.S)
_HEADED_DESCRIPTION = re.compile(r"^## Description\s*\n(.*?)(?=^## |\Z)", re.S | re.M)
_NOTES = re.compile(r"<!-- SECTION:NOTES:BEGIN -->(.*?)<!-- SECTION:NOTES:END -->", re.S)
_HOLDER = re.compile(r"^\*\*Holder:\*\* (\S+)[ \t]*$", re.M)
_CRITERIA = re.compile(r"<!-- AC:BEGIN -->(.*?)<!-- AC:END -->", re.S)
_ITEM = re.compile(r"^- \[([ xX])\] #(\d+) (.*?)[ \t]*$", re.M)
_NEEDS_ATTENTION = re.compile(
    r"^## Needs attention[ \t]*\n(.*?)(?=^## |<!-- SECTION:DESCRIPTION:END -->|\Z)", re.S | re.M
)


@dataclass(frozen=True)
class BacklogConfig:
    """What the board needs of `backlog/config.yml`."""

    statuses: tuple[str, ...]
    """The configured statuses in board order: the first is where a task starts, the last where it ends."""
    prefix: str
    """The task id prefix (`task` in `task-12`)."""
    project: str
    """The config's `project_name`, the team its tasks are in; empty when the config names none."""


def read_config(root: Path) -> BacklogConfig:
    """The config in `root/config.yml`, with upstream's defaults for the statuses and prefix it does not say.

    It has no default project: a project the config does not name is refused by `require_project`, never given a team.
    """
    try:
        raw = yaml.safe_load((root / "config.yml").read_text())
    except OSError, yaml.YAMLError:
        return BacklogConfig(DEFAULT_STATUSES, DEFAULT_PREFIX, "")
    raw = raw if isinstance(raw, dict) else {}
    statuses = tuple(str(s) for s in raw.get("statuses") or ()) or DEFAULT_STATUSES
    return BacklogConfig(
        statuses, str(raw.get("task_prefix") or DEFAULT_PREFIX), str(raw.get("project_name") or "").strip()
    )


def require_project(root: Path, config: BacklogConfig) -> str:
    """The project `config` names, which is the team of every task under `root`; refused when it names none."""
    if not config.project:
        raise ValueError(
            f"board: {root / 'config.yml'} sets no project_name, so its tasks belong to no team; name the project there"
        )
    return config.project


def upstream_keys(prefix: str = DEFAULT_PREFIX) -> TaskKeys:
    """Task keys `<prefix>-N` (and subtasks `<prefix>-N.M`) and the branches that name them, read in any case and
    named in the case of `prefix`."""
    number = r"\d+(?:\.\d+)*"
    head = re.escape(prefix)
    return TaskKeys(
        key=re.compile(rf"{head}-{number}", re.I),
        branch=re.compile(rf"(?:refs/heads/)?(?:[^/]+/)*?{head}-({number})(?=$|[-_/])", re.I),
        key_format=prefix.replace("{", "{{").replace("}", "}}") + "-{}",
    )


def canonical_key(prefix: str, key: str) -> str:
    """`key` with its prefix spelled as the configured `prefix` is (`task-45` is `TASK-45` for `TASK`); a key of another prefix is as written."""
    head, dash, rest = key.partition("-")
    return f"{prefix}-{rest}" if dash and head.casefold() == prefix.casefold() else key


def board_moves(
    machine: dict, writers: Mapping[str, tuple[Writer, ...]] = {}, lanes: Collection[str] | None = None
) -> dict[str, dict[str, Move]]:
    """The move verdicts out of each lane of a Board machine, by lane and then by the lane reached.

    A machine state that is not among `lanes` (a creation or archive state) is neither left nor reached; `None`
    counts every state as a lane.

    A move's writers are the actors the YAML declares for the events that make it; when any of those events
    declares none, anyone may make the move.
    """
    from starpulse.contracts.adapters import Move  # noqa: PLC0415 - import cost, paid on first use

    events: dict[tuple[str, str], list[str]] = {}
    for t in machine["transitions"]:
        if t["source"] != t["target"] and (lanes is None or {t["source"], t["target"]} <= set(lanes)):
            events.setdefault((t["source"], t["target"]), []).append(t["event"])
    moves: dict[str, dict[str, Move]] = {}
    for (source, target), names in events.items():
        declared = [writers.get(name, ()) for name in names]
        actors = () if not all(declared) else tuple(dict.fromkeys(w.actor for ws in declared for w in ws))
        moves.setdefault(source, {})[target] = Move(allowed=True, writers=actors)
    return moves


def _when(value: object) -> float | None:
    """A frontmatter date as epoch seconds: Backlog.md writes `YYYY-MM-DD HH:MM` or `YYYY-MM-DD` in UTC; None for anything else."""
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        for form in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                value = datetime.strptime(value.strip(), form)
                break
            except ValueError:
                continue
    return value.replace(tzinfo=UTC).timestamp() if isinstance(value, datetime) else None


def _strings(value: object) -> tuple[str, ...]:
    """Backlog's scalar-or-list metadata as the nonempty text values it holds."""
    values = value if isinstance(value, list) else [value]
    return tuple(text for item in values if item is not None and (text := str(item).strip()))


def _description(body: str) -> str:
    described = _DESCRIPTION.search(body) or _HEADED_DESCRIPTION.search(body)
    return described.group(1).strip() if described else ""


def _assignee(body: str) -> str:
    """The session a claim recorded in the task's notes: the last `**Holder:** <id>` line there, else empty.

    The marker lives in the notes because the Backlog CLI rewrites a task file's frontmatter and drops a key it
    does not know, while the notes section survives every edit.
    """
    notes = _NOTES.search(body)
    held = _HOLDER.findall(notes.group(1)) if notes else []
    return held[-1] if held else ""


def _criteria(body: str) -> list[tuple[bool, str]]:
    """Each acceptance criterion as whether it is checked and its text, in file order."""
    found = _CRITERIA.search(body)
    return [(mark != " ", text) for mark, _, text in _ITEM.findall(found.group(1))] if found else []


def _pause_reason(body: str, lane: str) -> str:
    """The first line of a `Needs attention` task's `## Needs attention` section, else empty."""
    found = _NEEDS_ATTENTION.search(body) if lane == "needs_attention" else None
    return next((line.strip() for line in found.group(1).splitlines() if line.strip()), "") if found else ""


def _notes(body: str) -> str:
    """The task's notes without the holder markers, trimmed; empty when it has none."""
    found = _NOTES.search(body)
    return _HOLDER.sub("", found.group(1)).strip() if found else ""


def _split(text: str) -> tuple[Any, str]:
    """A task file's YAML frontmatter and the Markdown after it; `(None, "")` for a file with neither."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1:
        return None, ""
    try:
        return yaml.load(text[4:end], Loader=_FrontmatterLoader), text[end + 4 :]
    except yaml.YAMLError:
        return None, ""


#: Each adapter whose thread is running, with that thread, so `stop_all` can end what a test started.
_live: dict[UpstreamBacklog, threading.Thread] = {}


def stop_all(timeout: float = 5.0) -> None:
    """Stop every running adapter thread and wait for each to end; the server never calls it, a test's teardown does."""
    for backlog, thread in list(_live.items()):
        backlog.stop()
        thread.join(timeout)


class UpstreamBacklog:
    """Reads one project's task files and hands each new or changed one to `put` as a `BoardTask`.

    `root` is the project's `backlog/` directory. A task under `tasks/` is in the lane of its status;
    one under `completed/` or `archive/tasks/` is settled; any other file is ignored, as is a task whose
    status the config does not list (it is logged once per change of the file).
    """

    def __init__(
        self,
        root: Path,
        put: Callable[[BoardTask], None],
        moves: Mapping[str, Mapping[str, Move]] | None = None,
        retract: Callable[[str], None] = lambda _task: None,
        files: Mapping[str, list] | None = None,
        kept: Callable[[dict[str, list]], None] = lambda _files: None,
        retired: Callable[[bool], Iterable[str] | None] = lambda _force=False: None,
    ) -> None:
        """`files` are the fingerprints a saved Board was placed from (`files`), so the first scan reads only the files
        changed since; `kept` is handed them after each scan that placed or retracted a task. `retired` streams the
        text of every retired task, or answers None while that is unchanged since it last answered (a `True` argument
        streams it regardless); a scan settles the ones in the done lane as completed, so a task depending on one is
        not left waiting on a file that is gone. Only their ids are kept, never their text."""
        self.root = root
        self.config = read_config(root)
        self._team = require_project(root, self.config)
        self._put = put
        self._retract = retract
        self._retired = retired
        self._settled_retired: set[str] = set()
        self._retired_done: set[str] = set()
        self._moves = moves if moves is not None else board_moves(board_machine(self.config.statuses))
        self._lanes = {lane_id(status) for status in self.config.statuses}
        self._seen: dict[Path, tuple[int, int]] = {}
        self._ids: dict[Path, str] = {}
        self._kept = kept
        self._stop = threading.Event()
        self._watching: DirWatch | None = None
        for name, (mtime_ns, size, task_id) in (files or {}).items():
            self._seen[root / name] = (mtime_ns, size)
            if task_id:
                self._ids[root / name] = task_id

    def files(self) -> dict[str, list]:
        """Each file scanned, by its path under the project, with its fingerprint and the task it holds (or None)."""
        return {
            str(path.relative_to(self.root)): [*fingerprint, self._ids.get(path)]
            for path, fingerprint in self._seen.items()
        }

    def scan(self) -> None:
        """Publish every task file that is new or changed since the last scan, and retract a task whose file is gone."""
        present: set[Path] = set()
        changed = False
        for folder, settled in _FOLDERS:
            for path in sorted((self.root / folder).glob("*.md")):
                present.add(path)
                changed |= self._place(path, settled)
        for gone in self._seen.keys() - present:
            self._forget(gone)
            changed = True
        self._settle(changed)
        if changed:
            self._kept(self.files())

    def scan_files(self, paths: Collection[Path]) -> None:
        """Do what `scan` does for `paths` alone: the files a watch named, without touching the rest of the board."""
        settled_by_folder = {self.root / folder: settled for folder, settled in _FOLDERS}
        changed = False
        for path in sorted(
            paths, key=lambda path: not path.exists()
        ):  # a file that arrived is placed before its old name goes
            if path.exists() and path.parent in settled_by_folder:
                changed |= self._place(path, settled_by_folder[path.parent])
            elif path in self._seen:
                self._forget(path)
                changed = True
        self._settle(changed)
        if changed:
            self._kept(self.files())

    def _place(self, path: Path, settled: Literal["completed", "archived"] | None) -> bool:
        """Publish the task `path` holds unless it is unchanged since last placed; whether the file's fingerprint moved."""
        try:
            stat = path.stat()
            fingerprint = (stat.st_mtime_ns, stat.st_size)
            if self._seen.get(path) == fingerprint:
                return False
            text = path.read_text()
        except OSError:
            return False  # moved or removed while scanning; the next scan sees where it went
        task = self._task(path, text, settled)
        if task is None:
            self._ids.pop(path, None)
        else:
            self._ids[path] = task.id
            self._put(task)
        self._seen[path] = (
            fingerprint  # noted once placed, so fingerprints kept mid-scan never claim a task the Board does not hold yet
        )
        return True

    def _forget(self, gone: Path) -> None:
        """Drop a file that is no longer there, retracting its task unless another file now holds it."""
        # a file moved between folders is back under its id; only an id no file holds is retracted
        task_id = self._ids.pop(gone, None)
        if task_id and task_id not in self._ids.values():
            self._retract(task_id)
            self._settled_retired.discard(task_id)  # no longer on the board, so a retired copy is placed again
        del self._seen[gone]

    def _settle(self, changed: bool) -> None:
        """Settle the retired tasks again when their rows changed, or the board's files did and left one unsettled.

        A file that leaves the board for the retired store is retracted with it, and a file back for a retired task
        displaces it, so the text is streamed again then even when `retired` answers None (unchanged)."""
        if (texts := self._retired(False)) is None and changed and self._retired_unsettled():
            texts = self._retired(True)
        if texts is not None:
            self._settle_retired(texts)

    def _retired_unsettled(self) -> bool:
        """Whether a retired done task is unplaced though no file holds it, or placed though a file does."""
        held = set(self._ids.values())
        return bool(self._settled_retired & held or self._retired_done - self._settled_retired - held)

    def _settle_retired(self, texts: Iterable[str]) -> None:
        """Place each retired task in the done lane as completed, and retract one no longer kept.

        A retired task that is not Done (archived before it was retired) stays unplaced, as it is once its file is
        gone; one whose file is back (restored) is the scan's to place."""
        placed: set[str] = set()
        done: set[str] = set()
        held = set(self._ids.values())
        for text in texts:
            task = self._task(self.root, text, "completed")
            if task is None or task.lane != _DONE_LANE:
                continue
            done.add(task.id)
            if task.id not in held:
                self._put(task)
                placed.add(task.id)
        for task_id in self._settled_retired - placed - held:
            self._retract(task_id)
        self._settled_retired, self._retired_done = placed, done

    def _task(self, path: Path, text: str, settled: Literal["completed", "archived"] | None) -> BoardTask | None:
        frontmatter, body = _split(text)
        if not isinstance(frontmatter, dict):
            return None
        task_id, title, status = (str(frontmatter.get(k) or "").strip() for k in ("id", "title", "status"))
        if not (task_id and title and status):
            return None
        task_id = canonical_key(self.config.prefix, task_id)
        lane = lane_id(status)
        if lane not in self._lanes and settled is None:
            logger.warning(
                "%s: status %r is not in %s's statuses; task skipped", path, status, self.root / "config.yml"
            )
            return None
        from starpulse.contracts.adapters import BoardTask  # noqa: PLC0415 - import cost, paid on first use

        assignees = _strings(frontmatter.get("assignee"))
        criteria = _criteria(body)
        dependencies = _strings(frontmatter.get("dependencies"))
        return BoardTask(
            id=task_id,
            title=title,
            team=self._team,
            lane=lane,
            dependencies=tuple(canonical_key(self.config.prefix, key) for key in dependencies),
            references=_strings(frontmatter.get("references")),
            settled=settled,
            created_at=_when(frontmatter.get("created_date")),
            settled_at=_when(frontmatter.get("updated_date")) if settled else None,
            assignee=assignees[0] if assignees else "",
            holder=_assignee(body),
            labels=_strings(frontmatter.get("labels")),
            milestone=str(frontmatter.get("milestone") or "").strip(),
            type=str(frontmatter.get("type") or "").strip(),
            description=_description(body),
            acceptance_criteria=tuple(text for _, text in criteria),
            acceptance_checked=tuple(checked for checked, _ in criteria),
            pause_reason=_pause_reason(body, lane),
            notes=_notes(body),
            moves={} if settled else dict(self._moves.get(lane, {})),
        )

    def start(
        self, interval: float = 2.0, scanned: Callable[[], None] = lambda: None
    ) -> threading.Thread:  # pragma: no mutate block — watch thread plumbing
        """Scan now, then place each file a watch names as it lands and rescan all of them every `interval` seconds,
        on a daemon thread, and return it; `scanned` runs once, after the first scan.

        The full scan is the backstop for an event the watch missed. Where the watch cannot start (no inotify), it is
        the only scan, and runs at least every `_POLL` seconds.
        """

        def run() -> None:
            watch = self._watching = self._watch()  # before the first scan, so a file written during it is not missed
            self.scan()
            scanned()
            try:
                while not self._stop.is_set():
                    if watch is None:
                        if self._stop.wait(min(interval, _POLL)):
                            break
                        self.scan()
                    elif (changed := watch.wait(interval)) is None:
                        self.scan()
                    elif changed:
                        self.scan_files(changed)
            finally:
                if watch:
                    watch.close()
                _live.pop(self, None)

        thread = threading.Thread(target=run, name="upstream-backlog", daemon=True)
        _live[self] = thread
        thread.start()
        return thread

    def stop(self) -> None:
        """End the thread `start` began: it leaves its loop at once, even while it waits out `interval`."""
        self._stop.set()
        if self._watching:
            self._watching.wake()

    def _watch(self) -> DirWatch | None:
        """A watch on the task folders, or None where the system cannot give one."""
        try:
            return DirWatch(self.root / folder for folder, _ in _FOLDERS)
        except OSError as error:
            logger.warning("%s: no file watch (%s); polling every %.0f s", self.root, error, _POLL)
            return None


#: The `[board]` settings this adapter reads: `path` is the project's `backlog/` directory, relative to the config;
#: `machine` a machine file for the Board, relative to the config; `command` the `backlog` CLI that writes moves.
_SETTINGS = {"type", "path", "interval", "machine", "command"}


def cli_writer(root: Path, statuses: tuple[str, ...], command: list[str]) -> MoveWriter:
    """A board writer that sets a status with the `backlog` CLI run in the project and answers with its output.

    A lane's status is the project's own spelling of it (`QA` for a move to `Qa`). An agent's claim (a move to
    `In Progress` that names its session) also appends the `**Holder:** <session>` marker to the task's notes, in
    the same edit as the status, so the board can say which session holds the task.
    """
    spelled = {lane_id(status): status for status in statuses}

    def write(task: str, status: str, actor: str, session: str = "") -> Written:
        argv = [*command, "task", "edit", task, "-s", spelled.get(lane_id(status), status)]
        if actor != "operator" and session and lane_id(status) == "in_progress":
            argv += ["--append-notes", f"**Holder:** {session}"]
        try:
            done = subprocess.run(argv, cwd=root.parent, capture_output=True, text=True, timeout=30.0, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return Written(False, f"{shlex.join(command)}: {error}")
        return Written(done.returncode == 0, "\n".join(filter(None, (done.stdout.strip(), done.stderr.strip()))))

    return write


def _machine(path: Path, config: BacklogConfig) -> tuple[Compiled, dict, list[dict]]:
    """The Board machine a file declares, compiled and drawn, with its cues, each beside the lane its event reaches;
    refused unless every lane is a state, every other state is initial or final, and each cued event reaches a lane."""
    from starpulse._internal.machines.machine_definition import load_machine  # noqa: PLC0415 - import cost, paid on first use
    from starpulse._internal.machines.snapshot import describe  # noqa: PLC0415 - import cost, paid on first use

    compiled = load_machine(path)
    drawn = describe(compiled.machine)
    ids = [lane_id(status) for status in config.statuses]
    states = {state["id"]: state for state in drawn["states"]}
    extra = {i for i, state in states.items() if i not in ids and not (state["initial"] or state["final"])}
    if mismatch := sorted(extra | (set(ids) - set(states))):
        raise ValueError(f"board: machine {path} and the project's statuses disagree on lanes {mismatch}")
    cues = []
    for cue in compiled.cues:
        if len(lanes := {t["target"] for t in drawn["transitions"] if t["event"] == cue.event} & set(ids)) != 1:
            raise ValueError(f"board: machine {path} cues on event {cue.event}, which must reach exactly one lane")
        cues.append({**asdict(cue), "state": lanes.pop()})
    return compiled, drawn, cues


def project_board(
    root: Path,
    settings: Mapping[str, Any],
    base: Path,
    writers: Callable[[BacklogConfig], Mapping[str, Any]],
    retired: Callable[[bool], Iterable[str] | None] = lambda _force=False: None,
) -> Board:
    """The Board of the Markdown project in `root`, polled every `settings["interval"]` seconds, with the writers `writers` builds.

    Any lane reaches any other unless `settings["machine"]` names a machine file (relative to `base`), whose transitions
    and `writers` then decide which moves are offered and to whom. `retired` is the scan's reader of retired task text.
    """
    interval = float(settings.get("interval", BACKSTOP))
    config = read_config(root)
    require_project(root, config)
    board_file = base / str(settings["machine"]) if "machine" in settings else None
    lane_ids = [lane_id(status) for status in config.statuses]
    if board_file:
        compiled, drawn, cues = _machine(board_file, config)
        declared = compiled.writers
    else:
        compiled, drawn, cues, declared = None, board_machine(config.statuses), [], {}

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        flows = {**({"board": compiled} if compiled else {}), **project_machines.load(base, board_file)}
        drawn_flows = project_machines.draw(flows, qualify, workflows)
        if compiled:
            drawn_flows["board"].setdefault("mainLine", [lane_id(status) for status in config.statuses])
        return {"board": drawn, **drawn_flows}

    def start(feed: BoardFeed, group: str, log: EventLog) -> None:
        # Built here, not at load: a `Move` is an adapter model, and a board read never starts the poll.
        # The first scan is the feed's replay: it places every file, the Ledger is built once at its end rather than
        # once per task, and a write meeting it waits for the task it places.
        # A restart resumes the Board the last run saved and re-reads only the files changed since it.
        feed.await_stream()
        files = None
        if feed.resume(log, _state_key(root, board_file), lambda _cursor: True) is not None:
            files = feed.source().get("files")
        moves = board_moves(drawn, declared, lane_ids)
        UpstreamBacklog(
            root,
            feed.put,
            moves,
            feed.retract,
            files=files,
            kept=lambda scanned: feed.keep_source({"files": scanned}),
            retired=retired,
        ).start(interval, scanned=lambda: feed.expect("0-0"))
        threading.Thread(target=feed.keep_saved, args=(threading.Event(),), name="board-state", daemon=True).start()

    return Board(
        machines=machines,
        start=start,
        keys=upstream_keys(config.prefix),
        cues=lambda qualify: cues,
        waits=compiled.waits if compiled else {},
        source=str(root),
        state_key=lambda: _state_key(root, board_file),
        **writers(config),
    )


def _state_key(root: Path, machine: Path | None) -> str:
    """The key a native board's Board is saved under: the project and a hash of the code, config and machine that
    project its tasks, so a change to any of them starts the next run from a full scan."""
    digest = hashlib.sha256()
    for name in _PROJECTION:
        digest.update(inspect.getsource(importlib.import_module(name)).encode())
    for path in (root / "config.yml", machine):
        if path is not None and path.is_file():
            digest.update(path.read_bytes())
    return f"native:{root.resolve()}@{digest.hexdigest()[:12]}"


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The Board of the Backlog.md project at `settings["path"]` (default `backlog`), polled every `interval` seconds.

    Moves are written with the `backlog` CLI (`command`).
    """
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    command = shlex.split(str(settings.get("command", "backlog")))
    root = base / str(settings.get("path", "backlog"))
    return project_board(root, settings, base, lambda config: {"writer": cli_writer(root, config.statuses, command)})
