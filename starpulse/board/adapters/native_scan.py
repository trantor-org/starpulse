"""The native board's scan: a project's task files in, the board contract out."""

import logging
import os
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal

import yaml

lazy from starpulse.contracts.adapters import BoardTask
lazy from starpulse.machine_engine.adapters.machine_loader import load_machine
lazy from starpulse.machine_engine.model.snapshot import describe

try:  # libyaml's loader: the same safe schema and errors, a tenth of the pure-Python parse time over a whole board
    from yaml import CSafeLoader as _FrontmatterLoader
except ImportError:
    from yaml import SafeLoader as _FrontmatterLoader

from starpulse.board.adapters import project_machines
from starpulse.board.model.claims import assignee_of
from starpulse.board.model.markdown import needs_attention_reason
from starpulse.board.model.policy import Policy, waits_of
from starpulse.contracts.task_keys import TaskKeys
from starpulse.contracts.tiers import DEFAULT_TIER, TIERS
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.transitions import DEFAULT_STATUSES, board_machine, board_moves, lane_id

if TYPE_CHECKING:
    from starpulse.contracts.adapters import Move
    from starpulse.machine_engine.model.machine_definition import Compiled
    from starpulse.machine_engine.model.workflow_names import Qualify

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "task"
#: Where a task file sits decides whether it is in a lane or has left them; subtasks are ids like `task-1.1`.
_FOLDERS: tuple[tuple[str, Literal["completed", "archived"] | None], ...] = (
    ("tasks", None),
    ("completed", "completed"),
    ("archive/tasks", "archived"),
)
_DESCRIPTION = re.compile(r"<!-- SECTION:DESCRIPTION:BEGIN -->(.*?)<!-- SECTION:DESCRIPTION:END -->", re.S)
_HEADED_DESCRIPTION = re.compile(r"^## Description\s*\n(.*?)(?=^## |\Z)", re.S | re.M)
_NOTES = re.compile(r"<!-- SECTION:NOTES:BEGIN -->(.*?)<!-- SECTION:NOTES:END -->", re.S)
_ASSIGNEE = re.compile(r"^\*\*Assignee:\*\* (\S+)[ \t]*$", re.M)
_CRITERIA = re.compile(r"<!-- AC:BEGIN -->(.*?)<!-- AC:END -->", re.S)
_ITEM = re.compile(r"^- \[([ xX])\] #(\d+) (.*?)[ \t]*$", re.M)


@dataclass(frozen=True)
class BacklogConfig:
    """What the board needs of `backlog/config.yml`."""

    statuses: tuple[str, ...]
    """The configured statuses in board order: the first is where a task starts, the last where it ends."""
    prefix: str
    """The task id prefix (`task` in `task-12`)."""
    project: str
    """The config's `project_name`, the team its tasks are in; empty when the config names none."""


def read_config(root: Path, statuses: tuple[str, ...] = ()) -> BacklogConfig:
    """The config in `root/config.yml`, with the defaults for the statuses and prefix it does not say.

    `statuses`, when given, are the board's lanes from the policy and replace the file's.

    It has no default project: a project the config does not name is refused by `require_project`, never given a team.
    """
    try:
        raw = yaml.safe_load((root / "config.yml").read_text())
    except OSError, yaml.YAMLError:
        raw = None
    raw = raw if isinstance(raw, dict) else {}
    statuses = statuses or tuple(str(s) for s in raw.get("statuses") or ()) or DEFAULT_STATUSES
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


def native_keys(prefix: str = DEFAULT_PREFIX) -> TaskKeys:
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
    size = len(prefix)
    matches = key[size : size + 1] == "-" and key[:size].casefold() == prefix.casefold()
    return f"{prefix}{key[size:]}" if matches else key


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


def _profile(frontmatter: dict) -> str:
    """The profile a task is routed to: its `profile` field, else empty."""
    profiles = _strings(frontmatter.get("profile"))
    return profiles[0] if profiles else ""


def _criteria(body: str) -> list[tuple[bool, str]]:
    """Each acceptance criterion as whether it is checked and its text, in file order."""
    found = _CRITERIA.search(body)
    return [(mark != " ", text) for mark, _, text in _ITEM.findall(found.group(1))] if found else []


def _pause_reason(body: str, lane: str, attention: str | None) -> str:
    """The first line of a `Needs attention` task's `## Needs attention` section, else empty."""
    return needs_attention_reason(body) if lane == attention else ""


def _marked(body: str) -> str:
    """The session of the last `**Assignee:** <id>` line in the task's notes, else empty: a claim written before the
    `assignee` front matter field is this marker."""
    found = _NOTES.search(body)
    marked = _ASSIGNEE.findall(found.group(1)) if found else []
    return marked[-1] if marked else ""


_COMMENTS = re.compile(r"<!-- COMMENTS:BEGIN -->(.*?)<!-- COMMENTS:END -->", re.S)


def _comments(body: str) -> str:
    """The text of the task's comments, trimmed; empty when it has none."""
    found = _COMMENTS.search(body)
    return found.group(1).strip() if found else ""


def _notes(body: str) -> str:
    """The task's notes without the claim markers, trimmed; empty when it has none."""
    found = _NOTES.search(body)
    return _ASSIGNEE.sub("", found.group(1)).strip() if found else ""


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


def dependencies(text: str) -> list[str]:
    """The task ids a task file's front matter lists under `dependencies`, empty for a file with none."""
    frontmatter, _ = _split(text)
    return list(_strings(frontmatter.get("dependencies"))) if isinstance(frontmatter, dict) else []


class NativeScan:
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
        retired: Callable[[bool], Iterable[str] | None] = lambda _force=False: None,
        refusal: Callable[[Mapping[str, Any], str, str], Mapping[str, Any] | None] = lambda *_: None,
        roles: StateRoles | None = None,
        readable: Callable[[Mapping[str, Any], str], str] = lambda *_: "",
        statuses: tuple[str, ...] = (),
    ) -> None:
        """`retired` streams the
        text of every retired task, or answers None while that is unchanged since it last answered (a `True` argument
        streams it regardless); a scan settles the ones in the done lane as completed, so a task depending on one is
        not left waiting on a file that is gone. Only their ids are kept, never their text. `refusal` answers, from a task's front matter and body and a lane,
        the update a rule that refuses the move there makes to it (`Move.actors` included), which the task's move to that
        lane then carries."""
        self.root = root.absolute()
        self.config = read_config(root, statuses)
        self._team = require_project(root, self.config)
        self._put = put
        self._retract = retract
        self._retired = retired
        self._settled_retired: set[str] = set()
        self._retired_done: set[str] = set()
        self._refusal = refusal
        self._readable = readable
        self._moves = moves if moves is not None else board_moves(board_machine(self.config.statuses))
        self._lanes = {lane_id(status) for status in self.config.statuses}
        self._roles = roles or StateRoles.of_statuses(self.config.statuses)
        # keyed by the listing's path string, so a scan of unchanged files builds no Path
        self._seen: dict[str, tuple[int, int]] = {}
        self._ids: dict[str, str] = {}

    def scan(self) -> int:
        """Publish every task file that is new or changed since the last scan, and retract a task whose file is gone;
        how many files that read or forgot.

        One `os.scandir` pass over the folders: a file whose time and size match the last scan is not read."""
        return len(self._scan())

    def start(self) -> None:
        """Scan once: no watch follows, since a task is read from its History, and a file is only the legacy import."""
        self.scan()

    def _scan(self) -> set[str]:
        present: set[str] = set()
        touched: set[str] = set()
        for folder, settled in _FOLDERS:
            for path, fingerprint in _listing(self.root / folder):
                present.add(path)
                if self._seen.get(path) != fingerprint and self._place(path, settled, fingerprint):
                    touched.add(path)
        gone = self._seen.keys() - present
        self._finish(gone, bool(touched))
        return touched | gone

    def _finish(self, gone: Iterable[str], changed: bool) -> None:
        for path in list(gone):
            self._forget(path)
            changed = True
        self._settle(changed)

    def _place(self, path: str, settled: Literal["completed", "archived"] | None, fingerprint: tuple[int, int]) -> bool:
        """Publish the task `path` holds, listed with `fingerprint`; whether it was read."""
        file = Path(path)
        try:
            text = file.read_text()
        except OSError:
            return False  # moved or removed while scanning; the next scan sees where it went
        task = self._task(file, text, settled)
        if task is None:
            self._ids.pop(path, None)
        else:
            self._ids[path] = task.id
            self._put(task)
        self._seen[path] = (
            fingerprint  # noted once placed, so fingerprints kept mid-scan never claim a task the Board does not hold yet
        )
        return True

    def _forget(self, gone: str) -> None:
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
            if task is None or task.lane != self._roles.done:
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
        criteria = _criteria(body)
        dependencies = _strings(frontmatter.get("dependencies"))
        tier = str(frontmatter.get("tier") or "").strip().lower()
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
            observed_at=_when(frontmatter.get("updated_date")) if lane == self._roles.done else None,
            profile=_profile(frontmatter),
            assignee=assignee_of(frontmatter) or _marked(body),
            labels=_strings(frontmatter.get("labels")),
            impact=str(frontmatter.get("impact") or "").strip().lower(),
            urgency=str(frontmatter.get("urgency") or "").strip().lower(),
            tier=tier if tier in TIERS else DEFAULT_TIER,
            adr_needed=str(frontmatter.get("adr_needed") or "").strip(),
            duplicate_search=str(frontmatter.get("duplicate_search") or "").strip(),
            duplicate_resolution=str(frontmatter.get("duplicate_resolution") or "").strip(),
            follows=str(frontmatter.get("follows") or "").strip(),
            milestone=str(frontmatter.get("milestone") or "").strip(),
            type=str(frontmatter.get("type") or "").strip(),
            aliases=_strings(frontmatter.get("aliases")),
            description=_description(body),
            acceptance_criteria=tuple(text for _, text in criteria),
            acceptance_checked=tuple(checked for checked, _ in criteria),
            pause_reason=_pause_reason(body, lane, self._roles.attention),
            notes=_notes(body),
            comments=_comments(body),
            moves={} if settled else self._offered(lane, frontmatter, body),
            readable="" if settled else self._readable(frontmatter, body),
        )

    def _offered(self, lane: str, frontmatter: dict, body: str) -> dict[str, Move]:
        """The moves out of `lane`, each refused when a board rule refuses it for this task."""
        moves = dict(self._moves.get(lane, {}))
        for target, move in moves.items():
            if refused := self._refusal(frontmatter, body, target):
                moves[target] = type(move).model_validate({**move.model_dump(), **refused})
        return moves


def _listing(folder: Path) -> list[tuple[str, tuple[int, int]]]:
    """Each `.md` file in `folder`, in name order, with its modification time and size; none when the folder is gone."""
    try:
        with os.scandir(folder) as entries:
            files = [entry for entry in entries if entry.name.endswith(".md") and entry.is_file()]
            files.sort(key=lambda entry: entry.name)
            stats = []
            for entry in files:
                try:
                    stat = entry.stat()
                except OSError:
                    continue  # removed mid-listing; the next scan sees where it went
                stats.append((entry.path, (stat.st_mtime_ns, stat.st_size)))
    except OSError:
        return []
    return stats


def _machine(
    path: Path, config: BacklogConfig, waits: Mapping[str, Mapping[str, str]]
) -> tuple[Compiled, dict, list[dict]]:
    """The Board machine a file declares, compiled and drawn, with the lanes' `waits` the policy DB holds, with its cues, each beside the lane its event reaches;
    refused when a cued event reaches no lane or several.

    A lane the machine and the statuses disagree on is tolerated: a state no status names is drawn empty, and a status no
    state names is off the board, so its tasks sit in no column and no move reaches it.
    """

    compiled = replace(load_machine(path), waits=waits)
    drawn = describe(compiled.machine)
    ids = [lane_id(status) for status in config.statuses]
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
    writers: Callable[[BacklogConfig, StateRoles], Mapping[str, Any]],
    statuses: tuple[str, ...] = (),
) -> SimpleNamespace:
    """The parts of the Board of the Markdown project in `root`, with the writers `writers` builds.

    Any lane reaches any other unless `settings["machine"]` names a machine file (relative to `base`), whose transitions
    and `writers` then decide which moves are offered and to whom. `statuses` are the lanes the policy holds, which
    replace the config file's.
    """
    config = read_config(root, statuses)
    require_project(root, config)
    board_file = base / str(settings["machine"]) if "machine" in settings else None
    lane_ids = [lane_id(status) for status in config.statuses]
    if board_file:
        compiled, drawn, cues = _machine(board_file, config, waits_of(settings.get("policy_rows") or Policy()))
    else:
        compiled, drawn, cues = None, board_machine(config.statuses), []
    roles = StateRoles.of_machine(compiled) if compiled else StateRoles.of_statuses(config.statuses)

    states = {state["id"] for state in drawn["states"]}

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        flows = {**({"board": compiled} if compiled else {}), **project_machines.load(base, board_file)}
        drawn_flows = project_machines.draw(flows, qualify, workflows)
        if compiled:
            drawn_flows["board"].setdefault("mainLine", [lane for lane in lane_ids if lane in states])
        return {"board": drawn, **drawn_flows}

    return SimpleNamespace(
        machines=machines,
        keys=native_keys(config.prefix),
        cues=lambda qualify: cues,
        waits=compiled.waits if compiled else {},
        roles=roles,
        source=str(root),
        **writers(config, roles),
    )
