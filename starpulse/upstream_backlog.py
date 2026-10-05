"""The upstream Backlog.md adapter: a project's task files in, the board contract out.

Upstream Backlog.md (MrLesk/Backlog.md) has no projection stream and no server to ask; its state is
the Markdown files under the project's `backlog/` directory. `UpstreamBacklog` polls them, hands each
changed file to a feed as a `BoardTask`, and the Board machine comes from the project's own statuses
(`backlog/config.yml`), so a lane is a status the project configured. It imports neither Redis nor the
projection contract, so it runs on a machine that has neither. It is the default `[board]` adapter.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml

from starpulse.board import Board, MoveWriter, Written
from starpulse.contracts import BoardTask, Move, TaskKeys
from starpulse.machine_definition import Writer, load_machine
from starpulse.snapshot import Qualify, describe

if TYPE_CHECKING:
    from starpulse.board_feed import BoardFeed

logger = logging.getLogger(__name__)

#: Upstream's own defaults, used for a project with no `config.yml`.
DEFAULT_STATUSES = ("To Do", "In Progress", "Done")
DEFAULT_PREFIX = "task"
#: Where a task file sits decides whether it is in a lane or has left them; subtasks are ids like `task-1.1`.
_FOLDERS: tuple[tuple[str, Literal["completed", "archived"] | None], ...] = (
    ("tasks", None),
    ("completed", "completed"),
    ("archive/tasks", "archived"),
)
_DESCRIPTION = re.compile(r"<!-- SECTION:DESCRIPTION:BEGIN -->(.*?)<!-- SECTION:DESCRIPTION:END -->", re.S)
_HEADED_DESCRIPTION = re.compile(r"^## Description\s*\n(.*?)(?=^## |\Z)", re.S | re.M)


@dataclass(frozen=True)
class BacklogConfig:
    """What the board needs of `backlog/config.yml`."""

    statuses: tuple[str, ...]
    """The configured statuses in board order: the first is where a task starts, the last where it ends."""
    prefix: str
    """The task id prefix (`task` in `task-12`)."""


def read_config(root: Path) -> BacklogConfig:
    """The config in `root/config.yml`, with upstream's defaults for what it does not say."""
    try:
        raw = yaml.safe_load((root / "config.yml").read_text())
    except OSError, yaml.YAMLError:
        return BacklogConfig(DEFAULT_STATUSES, DEFAULT_PREFIX)
    raw = raw if isinstance(raw, dict) else {}
    statuses = tuple(str(s) for s in raw.get("statuses") or ()) or DEFAULT_STATUSES
    return BacklogConfig(statuses, str(raw.get("task_prefix") or DEFAULT_PREFIX))


def upstream_keys(prefix: str = DEFAULT_PREFIX) -> TaskKeys:
    """Task keys `<prefix>-N` (and subtasks `<prefix>-N.M`) and the branches that name them, in any case."""
    key = rf"{re.escape(prefix)}-\d+(?:\.\d+)*"
    return TaskKeys(
        key=re.compile(key, re.I),
        branch=re.compile(rf"(?:refs/heads/)?(?:[^/]+/)*?({key})(?=$|[-_/])", re.I),
    )


def lane_id(status: str) -> str:
    """A status as the Board machine's state id: lower-cased, spaces as `_`."""
    return status.lower().replace(" ", "_")


def board_machine(statuses: tuple[str, ...]) -> dict:
    """The Board machine a project's statuses make: a state each, and a transition between any two.

    Backlog.md lets a task move to any status, so the machine does too; `to_<state>` names the event.
    """
    ids = [lane_id(status) for status in statuses]
    return {
        "states": [
            {"id": lane_id(s), "name": s, "initial": i == 0, "final": i == len(statuses) - 1}
            for i, s in enumerate(statuses)
        ],
        "transitions": [
            {"source": source, "target": target, "event": f"to_{target}"}
            for source in ids
            for target in ids
            if source != target
        ],
        "mainLine": ids,
    }


def board_moves(machine: dict, writers: Mapping[str, tuple[Writer, ...]] = {}) -> dict[str, dict[str, Move]]:
    """The move verdicts out of each lane of a Board machine, by lane and then by the lane reached.

    A move's writers are the actors the YAML declares for the events that make it; when any of those events
    declares none, anyone may make the move.
    """
    events: dict[tuple[str, str], list[str]] = {}
    for t in machine["transitions"]:
        if t["source"] != t["target"]:
            events.setdefault((t["source"], t["target"]), []).append(t["event"])
    moves: dict[str, dict[str, Move]] = {}
    for (source, target), names in events.items():
        declared = [writers.get(name, ()) for name in names]
        actors = () if not all(declared) else tuple(dict.fromkeys(w.actor for ws in declared for w in ws))
        moves.setdefault(source, {})[target] = Move(allowed=True, writers=actors)
    return moves


def _strings(value: object) -> tuple[str, ...]:
    """Backlog's scalar-or-list metadata as the nonempty text values it holds."""
    values = value if isinstance(value, list) else [value]
    return tuple(text for item in values if item is not None and (text := str(item).strip()))


def _description(body: str) -> str:
    described = _DESCRIPTION.search(body) or _HEADED_DESCRIPTION.search(body)
    return described.group(1).strip() if described else ""


def _split(text: str) -> tuple[Any, str]:
    """A task file's YAML frontmatter and the Markdown after it; `(None, "")` for a file with neither."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1:
        return None, ""
    try:
        return yaml.safe_load(text[4:end]), text[end + 4 :]
    except yaml.YAMLError:
        return None, ""


class UpstreamBacklog:
    """Reads one project's task files and hands each new or changed one to `put` as a `BoardTask`.

    `root` is the project's `backlog/` directory. A task under `tasks/` is in the lane of its status;
    one under `completed/` or `archive/tasks/` is settled; any other file is ignored, as is a task whose
    status the config does not list (it is logged once per change of the file).
    """

    def __init__(
        self, root: Path, put: Callable[[BoardTask], None], moves: Mapping[str, Mapping[str, Move]] | None = None
    ) -> None:
        self.root = root
        self.config = read_config(root)
        self._put = put
        self._moves = moves if moves is not None else board_moves(board_machine(self.config.statuses))
        self._lanes = {lane_id(status) for status in self.config.statuses}
        self._seen: dict[Path, tuple[int, int]] = {}

    def scan(self) -> None:
        """Publish every task file that is new or changed since the last scan."""
        present: set[Path] = set()
        for folder, settled in _FOLDERS:
            for path in sorted((self.root / folder).glob("*.md")):
                present.add(path)
                try:
                    stat = path.stat()
                    fingerprint = (stat.st_mtime_ns, stat.st_size)
                    if self._seen.get(path) == fingerprint:
                        continue
                    text = path.read_text()
                except OSError:
                    continue  # moved or removed while scanning; the next scan sees where it went
                self._seen[path] = fingerprint
                if (task := self._task(path, text, settled)) is not None:
                    self._put(task)
        for gone in self._seen.keys() - present:
            del self._seen[gone]

    def _task(self, path: Path, text: str, settled: Literal["completed", "archived"] | None) -> BoardTask | None:
        frontmatter, body = _split(text)
        if not isinstance(frontmatter, dict):
            return None
        task_id, title, status = (str(frontmatter.get(k) or "").strip() for k in ("id", "title", "status"))
        if not (task_id and title and status):
            return None
        lane = lane_id(status)
        if lane not in self._lanes and settled is None:
            logger.warning(
                "%s: status %r is not in %s's statuses; task skipped", path, status, self.root / "config.yml"
            )
            return None
        assignees = _strings(frontmatter.get("assignee"))
        return BoardTask(
            id=task_id,
            title=title,
            lane=lane,
            dependencies=_strings(frontmatter.get("dependencies")),
            references=_strings(frontmatter.get("references")),
            settled=settled,
            assignee=assignees[0] if assignees else "",
            labels=_strings(frontmatter.get("labels")),
            description=_description(body),
            moves={} if settled else dict(self._moves.get(lane, {})),
        )

    def start(self, interval: float = 2.0) -> threading.Thread:  # pragma: no mutate block — polling thread plumbing
        """Scan now and then every `interval` seconds on a daemon thread, and return it."""

        def run() -> None:
            while True:
                self.scan()
                time.sleep(interval)

        thread = threading.Thread(target=run, name="upstream-backlog", daemon=True)
        thread.start()
        return thread


#: The `[board]` settings this adapter reads: `path` is the project's `backlog/` directory, relative to the config;
#: `machine` a machine file for the Board, relative to the config; `command` the `backlog` CLI that writes moves.
_SETTINGS = {"type", "path", "interval", "machine", "command"}


def cli_writer(root: Path, statuses: tuple[str, ...], command: list[str]) -> MoveWriter:
    """A board writer that sets a status with the `backlog` CLI run in the project and answers with its output.

    A lane's status is the project's own spelling of it (`QA` for a move to `Qa`).
    """
    spelled = {lane_id(status): status for status in statuses}

    def write(task: str, status: str, actor: str) -> Written:
        argv = [*command, "task", "edit", task, "-s", spelled.get(lane_id(status), status)]
        try:
            done = subprocess.run(argv, cwd=root.parent, capture_output=True, text=True, timeout=30.0, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return Written(False, f"{shlex.join(command)}: {error}")
        return Written(done.returncode == 0, "\n".join(filter(None, (done.stdout.strip(), done.stderr.strip()))))

    return write


def _machine(path: Path, config: BacklogConfig) -> tuple[dict, dict[str, tuple[Writer, ...]]]:
    """The Board machine a file declares, drawn, with its writers; refused unless its states are the project's lanes."""
    compiled = load_machine(path)
    drawn = describe(compiled.machine)
    ids = [lane_id(status) for status in config.statuses]
    if mismatch := sorted(set(ids) ^ {state["id"] for state in drawn["states"]}):
        raise ValueError(f"board: machine {path} and the project's statuses disagree on lanes {mismatch}")
    return {**drawn, "mainLine": ids}, dict(compiled.writers)


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The Board of the Backlog.md project at `settings["path"]` (default `backlog`), polled every `interval` seconds.

    Moves are written with the `backlog` CLI (`command`). Any lane reaches any other unless `machine` names a machine
    file, whose transitions and `writers` then decide which moves are offered and to whom.
    """
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    root = base / str(settings.get("path", "backlog"))
    interval = float(settings.get("interval", 2.0))
    config = read_config(root)
    if "machine" in settings:
        drawn, writers = _machine(base / str(settings["machine"]), config)
    else:
        drawn, writers = board_machine(config.statuses), {}
    moves = board_moves(drawn, writers)

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        return {"board": drawn}

    def start(feed: BoardFeed, group: str) -> None:
        UpstreamBacklog(root, feed.put, moves).start(interval)

    return Board(
        machines=machines,
        start=start,
        keys=upstream_keys(config.prefix),
        writer=cli_writer(root, config.statuses, shlex.split(str(settings.get("command", "backlog")))),
        source=str(root),
    )
