"""The task actor's fact functions: a pure derivation over the lane checks, reading and writing through `TaskFacts`.

A fact function answers `(proof, comment)` when the fact holds for a task, else None. It imports nothing that does I/O:
every read of the board, the pull request store, the holder probe or the actor's own memory is a `TaskFacts` read,
and every effect (a hold comment, the unsettled flag, the pin and held sets) a `TaskFacts` command, so the actor's
adapter alone touches the world (ADR Every Task State Re-Derives on One Trigger Set Through the Task Actor).
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from starpulse.board.model import criteria
from starpulse.board.model.acceptance import resolved
from starpulse.board.model.markdown import (
    ANSWER_COMMENT,
    ARCHIVE_ANSWER,
    ARCHIVE_REQUEST,
    ASK_REQUEST,
    FREEZE_REQUEST,
    MOVE_REQUEST,
    NO_MERGE,
    UNFREEZE_REQUEST,
    WAIT_REQUEST,
    attention_reason,
    needs_attention_reason,
)
from starpulse.board.model.rollup import checks_verdict
from starpulse.board.model.seam import HELD, MERGE_EVIDENCE

#: The question that ends the `## Needs attention` reason of a task the actor moves there on a pull request fact.
ATTENTION_QUESTION = "Fix it on the task branch and redeliver, or rescope?"
#: The options a Needs attention ask offers for a task whose session ended with work left.
RESTART_OR_RESCOPE = ("restart it in a new session", "rescope the task")
#: What an uncited-pull-request ask says after the task's id: a cited pull request settles it.
UNCITED_ASK = "has an uncited pull request."
DONE_HELD = "Held from Done:"
#: The comment the actor writes beside a request it leaves standing: a request it cannot act on stays the pending one.
ACTOR_NOTES = (DONE_HELD,)
#: The opening of the reason the task actor gives a task it parks on a failed step, a refused write or an illegal move.
FAULT = "Task actor fault:"
#: The line under that reason: how the operator leaves Needs attention once the cause is fixed.
FAULT_NEXT = "Fix the cause, then move the task back to In Progress; the actor does not retry it."
#: The opening of the comment `backlog-task update --pushback` records.
PUSHBACK = "Operator pushback:"
#: The opening of the comment the actor writes when operator feedback sends a Review task back to its holder.
SENT_BACK = "Sent back for operator feedback:"
#: The opening of the comment a holder records once the feedback it was sent back for is addressed: what changed, or why
#: nothing did. It is the reply that releases the hold.
ADDRESSED = "Feedback addressed:"
#: The pull request states that end a pull request.
TERMINAL = ("MERGED", "CLOSED")
#: A Waiting task's service level expectation: seconds from entering Waiting, or past its latest `expect_by`.
DAY_S = 86_400.0
SLE_DAYS, GRACE_DAYS = 7, 2

Agent = dict[str, Any]
Held = tuple[Any, str] | None


class Roles(Protocol):
    """The lanes of the board's machine a fact names by role."""

    working: str
    review: str
    attention: str


class TaskFacts(Protocol):
    """What a fact function reads and commands: the actor's adapter implements it over the live feed, store and probes."""

    @property
    def roles(self) -> Roles: ...
    @property
    def board_repo(self) -> str: ...

    def now(self) -> float: ...
    def record(self, url: str) -> dict[str, Any] | None: ...
    def own_prs(self, agent: Agent) -> list[str]: ...
    def unlinked(self, agent: Agent) -> list[str]: ...
    def landed(self, record: dict[str, Any]) -> bool: ...
    def memory(self, name: str) -> Mapping[str, Any]: ...
    def comments(self, agent: Agent) -> list[str] | None: ...
    def dependency_needs(self, name: str) -> Sequence[str]: ...
    def unfinished(self, name: str) -> tuple[str, ...]: ...
    def started(self, name: str) -> bool: ...
    def alive(self, name: str) -> bool | None: ...
    def holds(self, name: str) -> tuple[str, ...] | None: ...
    def owns_failure(self, name: str) -> bool: ...
    def settling(self, name: str) -> bool: ...
    def main_green(self) -> str | None: ...
    def is_open(self, name: str) -> bool: ...
    def is_done(self, name: str) -> bool: ...
    def is_archived(self, name: str) -> bool: ...
    def task(self, name: str) -> dict[str, Any] | None: ...
    def open_tasks(self) -> list[dict[str, Any]]: ...
    def machine_task(self, phase: str, name: str) -> dict[str, Any] | None: ...
    def phases(self) -> list[str]: ...
    def sequence(self, agent: Agent) -> Sequence[str]: ...
    def waiting_on(self, agent: Agent) -> str | None: ...
    def heard(self, name: str) -> Sequence[str]: ...
    def unpublished(self, subject: str) -> str | None: ...

    def unsettled(self) -> None: ...
    def hooked(self) -> None: ...
    def note_hold(self, agent: Agent, reasons: tuple[str, ...], prefix: str = HELD) -> None: ...
    def pin_held(self, name: str, on: bool) -> None: ...
    def held(self, name: str, on: bool) -> None: ...


def epoch(text: str) -> float | None:
    """Epoch seconds of an ISO date or timestamp (UTC when it names no zone); None when it is neither."""
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def stamp(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d")


def need_of(need: str) -> tuple[str, int]:
    """`(task, criterion number)` of a dependency need `TASK-N#K`; a need that names no number is number 0, which
    no task has."""
    task, _, number = need.partition("#")
    return task, int(number) if number.isdigit() else 0


def cleared(facts: TaskFacts, dependency: str) -> bool:
    """Whether the dependency is done, or archived: its file left the lanes without reaching Done."""
    return facts.is_done(dependency) or facts.is_archived(dependency)


def missing(facts: TaskFacts, agent: Agent) -> tuple[str, ...]:
    """The dependencies the Board holds in no store: no open task, none done, none archived. Nothing finishes them."""
    return tuple(
        dependency
        for dependency in agent["dependencies"]
        if not facts.is_open(dependency) and not cleared(facts, dependency)
    )


def dead(facts: TaskFacts, agent: Agent) -> tuple[str, ...]:
    """Why the task's wait can never end: a dependency the board holds in no store, one archived without leaving the
    task's dependencies while another open dependency or Start Criteria still gate it, or event subjects none of which is heard or published by a component."""
    reasons = [f"{name} is not on the board" for name in missing(facts, agent)]
    if unmet(facts, agent) or criteria.authored(agent["description"]):
        reasons += [f"{name} is archived and never reaches Done" for name in agent["dependencies"] if facts.is_archived(name) and not facts.is_done(name)]
    gate = criteria.subjects(agent["description"])
    if gate and not facts.heard(agent["id"]) and all(unpublished := [facts.unpublished(each) for each in gate]):
        reasons += unpublished
    return tuple(reasons)


def entered(facts: TaskFacts, agent: Agent) -> float:
    """When `agent` entered the Board lane it holds, as read at the move: the feed's `entered` is its newest event of
    any kind, which a comment after a verdict moves past the verdict's time."""
    lane, at = facts.memory(agent["id"]).get("lane_entered") or ("", 0.0)
    return at if lane == agent["state"] else agent.get("entered") or 0.0


def proof_prs(facts: TaskFacts, agent: Agent) -> list[str]:
    """The pull requests whose ends prove a task's work. In Review, a task with no own pull request merged or open
    takes every cited one: another task's delivery may have superseded its own, which closed unmerged or never
    existed. An own pull request still open keeps a merged reference from standing for the task's delivery."""
    own = facts.own_prs(agent)
    if agent["state"] != facts.roles.review:
        return own
    if any((record := facts.record(url)) and record["state"] != "CLOSED" for url in own):
        return own
    return agent["prs"]


def merged_at(facts: TaskFacts, agent: Agent) -> float | None:
    """When the latest of the pull requests that proved `agent`'s work merged."""
    merges = (
        epoch(record["mergedAt"])
        for url in proof_prs(facts, agent)
        if (record := facts.record(url)) and record["state"] == "MERGED" and record["mergedAt"]
    )
    return max((at for at in merges if at is not None), default=None)


def replies(texts: Iterable[str]) -> int:
    """How many comments record that operator feedback is addressed."""
    return sum(text.strip().startswith(ADDRESSED) for text in texts)


def feedback_held(facts: TaskFacts, agent: Agent) -> bool:
    """Whether the task was sent back from Review and its holder has not replied since: the reply count its send-back
    recorded still stands. A comment read that fails holds."""
    replied = facts.memory(agent["id"]).get("sent_back")
    legacy = isinstance(replied, Mapping) and bool(replied)
    if not legacy and not isinstance(replied, int):
        return False
    if (texts := facts.comments(agent)) is None:
        facts.unsettled()
        return True
    if legacy:  # a hold recorded by head before it counted replies: held until one follows the newest send-back
        sent = max((i for i, text in enumerate(texts) if text.strip().startswith(SENT_BACK)), default=-1)
        return replies(texts[sent + 1 :]) == 0
    return replies(texts) <= replied


def why_unready(record: dict[str, Any], held: bool) -> list[str]:
    """The conditions that keep a pull request record from being ready: draft, conflicting, a mergeability GitHub has not
    settled, checks that are not passed, or held after a send-back until its holder replies."""
    verdict = checks_verdict(
        record["state"], record["checks"], record["headRefOid"], record["rollup"], record["requiredChecks"]
    )
    return [
        reason
        for reason, holds in (
            ("draft", record["isDraft"]),
            ("conflicting", record["mergeable"] == "CONFLICTING"),
            ("mergeability not settled", record["mergeable"] not in ("MERGEABLE", "CONFLICTING")),
            (f"checks {verdict}", verdict != "pass"),
            ("held after a send-back until the holder replies", held),
        )
        if holds
    ]


def unready(facts: TaskFacts, agent: Agent) -> str | None:
    """Why each open pull request of the task's own delivery is not ready, else None."""
    held = feedback_held(facts, agent)
    parts = []
    for url in facts.own_prs(agent):
        record = facts.record(url)
        if record is not None and record["state"] == "OPEN" and (why := why_unready(record, held)):
            parts.append(f"{record['repo']}#{record['number']} {', '.join(why)}")
    return "; ".join(parts) or None


def closed_lane(facts: TaskFacts, name: str, end_lanes: Collection[str]) -> bool:
    """Whether `name` sits in a lane where its holder's session ends once idle (`end_lanes`). An archived task has no
    lean record, so the archive names its lane."""
    agent = facts.task(name)
    return (agent["state"] if agent else "archived" if facts.is_archived(name) else None) in end_lanes


def pr_terminal(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The merge evidence when the task cites pull requests and every one has ended, else None. A check task that
    cites only other tasks' pull requests has no delivery of its own to wait for: its checked criteria close it.
    Review proves its work on `proof_prs`; every other lane still waits on its own pull requests only. In the
    working lane the latest merge must follow the task's work floor."""
    own = facts.own_prs(agent)
    if not own and agent["prs"] and agent["type"] == "check":
        if not all(criterion["checked"] for criterion in agent.get("criteria", ())):
            return None
        proof = f"no pull request of its own; cites {', '.join(agent['prs'])}"
        return proof, f"{MERGE_EVIDENCE} {proof}"
    parts = []
    proved = proof_prs(facts, agent)
    for url in proved:
        record = facts.record(url)
        if record is None or record["state"] not in TERMINAL:
            return None
        if record["state"] == "MERGED" and not record["mergedAt"]:
            return None  # merged on an event's word alone: the next read of GitHub settles it
        link = f"PR #{record['number']}" if record["repo"] == facts.board_repo else url
        if record["state"] == "MERGED" and not facts.landed(record):
            # merged into an integration branch not yet on main: the work is not delivered
            facts.note_hold(agent, (f"{link} merged into {record['baseRefName']}, not main",), DONE_HELD)
            return None
        part = f"{record['repo']}#{record['number']} {record['state'].lower()}"
        if record["mergeSha"]:
            part += f" as {record['mergeSha']}"
        parts.append(f"{part} ({link})")
    if not parts:
        return None
    if unlinked := facts.unlinked(agent):
        # an open pull request naming the task is its delivery too: one cited merge never ends it
        if any(facts.record(url)["state"] == "MERGED" for url in proved):
            facts.note_hold(agent, (f"open pull requests name it but it does not cite them: {', '.join(unlinked)}",), DONE_HELD)
        return None
    merged = merged_at(facts, agent)
    if (
        agent["state"] == facts.roles.working
        and merged is not None
        and merged < work_floor(facts, agent)
    ):
        return None  # the merge predates the work floor: a reopened task's earlier delivery proves nothing
    # the board's guard wants the evidence to name every cited pull request: a reference is named as one, not proof
    if references := [url for url in agent["prs"] if url not in proved]:
        parts.append(f"cites as a reference, not proof: {', '.join(references)}")
    proof = "; ".join(parts)
    return proof, f"{MERGE_EVIDENCE} {proof}"


def work_floor(facts: TaskFacts, agent: Agent) -> float:
    """When the working lane's shipped work stops counting: the task's last entry other than an answer out of Needs
    attention, kept in memory on each entry. A task with none counts every merge: the feed's newest event time is no entry."""
    return facts.memory(agent["id"]).get("work_floor") or 0.0


def pr_merged(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The merge evidence when every pull request the task cites has ended and at least one merged, else None: a
    delivery closed unmerged is no proof of the work. A closed one beside a merged one stays cited for the audit
    trail and is named closed in the evidence, which the board's proof guard asks to name every cited one. A Needs
    attention task with work unfinished stays asked: its merge closes it only once nothing is left."""
    terminal = pr_terminal(facts, agent)
    records = [facts.record(url) for url in proof_prs(facts, agent)]
    merged = any(record and record["state"] == "MERGED" for record in records)
    if not (terminal and merged) or (agent["state"] == facts.roles.attention and facts.unfinished(agent["id"])):
        return None
    return terminal


def pr_closed_unmerged(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The closed pull requests and the question when every pull request the task cites has ended and none merged:
    its delivery is gone, and the operator picks a redelivery or the archive."""
    terminal = pr_terminal(facts, agent)
    records = [facts.record(url) for url in proof_prs(facts, agent)]
    if not terminal or any(not record or record["state"] != "CLOSED" for record in records):
        return None
    return terminal[0], attention_reason(
        f"Every pull request the task cites closed unmerged: {', '.join(proof_prs(facts, agent))}",
        "its delivery is gone",
        ("redeliver it on a new pull request", "archive the task"),
        "Redeliver or archive?",
    )


def closed_answer(facts: TaskFacts, agent: Agent, texts: Sequence[str], ask: str) -> str | None:
    """The operator's answer after the last `ask` comment once the task's session has settled, else None: a session that
    ended its turn on the answer redelivered nothing."""
    if not facts.settling(agent["id"]):
        return None
    asked = [index for index, text in enumerate(texts) if text.strip() == ask.strip()]
    return next((text.strip() for text in texts[asked[-1] + 1 :] if ANSWER_COMMENT.match(text)), None) if asked else None


def pr_closed_unmerged_complete(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The closed pull requests and the statement when `pr_closed_unmerged` holds, every criterion is checked and a
    comment opens `NO_MERGE`: the work landed elsewhere or needed no merge, so nothing is left to ask. At the task's
    session settle the operator's answer after the last ask is the statement too: a session that ended its turn on it
    redelivered nothing. A checked task with neither is a rejected change: `pr_closed_unmerged` asks about it."""
    closed = pr_closed_unmerged(facts, agent)
    ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
    if not closed or not ticks or not all(ticks):
        return None
    if (texts := facts.comments(agent)) is None:
        facts.unsettled()
        return None
    statement = next((text.strip() for text in texts if text.strip().startswith(NO_MERGE)), None)
    if statement is None:
        answer = closed_answer(facts, agent, texts, closed[1])
        statement = None if answer and ARCHIVE_ANSWER.match(answer) else answer  # an archive answer archives
    if statement is None:
        return None
    return closed[0], f"Every pull request it cites closed unmerged, every criterion is checked: {closed[0]}. {statement}"


def pr_merged_unfinished(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The merge evidence and what is left when the task's pull requests merged and the board reports work
    unfinished, else None, as the Needs attention reason naming its cause bug. A command that fails reports its
    error: the task is asked about, never closed."""
    merged = pr_merged(facts, agent)
    if merged is None or not (left := facts.unfinished(agent["id"])):
        return None
    proof, comment = merged
    return (proof, left), attention_reason(
        f"{comment} Unfinished: {'; '.join(left)} (cause bug TASK-15922)",
        "its pull request merged with work left",
        ("deliver the rest in a new session", "rescope the task"),
        "Which?",
    )


def criteria_checked(facts: TaskFacts, agent: Agent) -> tuple[int, str] | None:
    """The criteria count when every criterion is checked or struck and the task ships no pull request: its phase
    sequence has no `deliver`, or it cites none and its final summary is recorded. An open pull request naming the task
    and a cited one that has not ended hold it either way, except an open draft a no-`deliver` task cites, handed to a follow-up task. A task with no criteria (an audit signal) always needs that final summary and no pull request.
    A task citing none whose board reports work unfinished (`unfinished`: a built branch not on main) is held from Done
    under `DONE_HELD`."""
    ticks = [resolved(criterion) for criterion in agent.get("criteria", ())]
    if not all(ticks):
        return None
    if facts.unlinked(agent):
        return None  # an open pull request naming the task is its delivery, whatever its phase sequence says
    ships_pr = "deliver" in facts.sequence(agent)
    if any(
        (record := facts.record(url)) is None
        or (record["state"] not in TERMINAL and (ships_pr or not record.get("isDraft")))
        for url in facts.own_prs(agent)
    ):
        # a pull request it cites that has not ended is not shipped nothing; a no-deliver task's open draft is a
        # handed-off one a follow-up task delivers
        return None
    if (ships_pr or not ticks) and (
        facts.own_prs(agent) or not (agent.get("final_summary") or "").strip()
    ):
        return None
    if not facts.own_prs(agent) and (left := facts.unfinished(agent["id"])):
        facts.note_hold(agent, tuple(left), DONE_HELD)  # a built branch not on main is delivered first, never closed
        return None
    shown = f"Every criterion is checked ({len(ticks)})" if ticks else "The task has no criteria"
    return len(ticks), f"{shown} and the task ships no pull request."


def pr_ready(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The ready or merged pull requests when the task cites one and no open one of them is unready, else None; a
    closed pull request is no delivery and holds nothing. A task sent back from Review
    stays put until its holder records the feedback addressed (`ADDRESSED`): a new head is no reply. An open pull request is ready only when it does not conflict with its base and the rollup of
    its current head says every required check passed (`checks_verdict`): a required check not posted is not green,
    a push re-arms the gate, and a repository whose ruleset requires none rolls up passed as soon as the pull
    request is not a draft. A task in Needs attention whose `## Needs attention` ask stays there, answered or not (the
    answer's resume moves it to In Progress, and a bounce to Review would race it),
    unless its ask ends in the actor's own failing-checks question (`ATTENTION_QUESTION`) or is the uncited-pull-request
    ask (`UNCITED_ASK`): a ready cited pull request settles both, and `unlinked` still holds while one stays uncited."""
    reason = needs_attention_reason(agent["description"])
    if (
        agent["state"] == facts.roles.attention
        and reason
        and not reason.endswith(ATTENTION_QUESTION)
        and f" {UNCITED_ASK}" not in reason
    ):
        return None
    parts = []
    held = feedback_held(facts, agent)
    # In the working lane a PR merged before the work floor is shipped work (a post-merge send back).
    floor = work_floor(facts, agent) if agent["state"] == facts.roles.working else 0.0
    for url in facts.own_prs(agent):
        record = facts.record(url)
        if record is None:
            continue
        merged = record["state"] == "MERGED" and record["mergedAt"]
        if merged and (epoch(record["mergedAt"]) or 0.0) < floor:
            continue
        if merged:
            parts.append(f"{record['repo']}#{record['number']} merged")
        elif record["state"] == "OPEN":
            if why_unready(record, held):
                return None  # Review waits for the last open pull request to go green
            parts.append(f"{record['repo']}#{record['number']} ready")
    if not parts or facts.unlinked(agent):
        return None  # an open pull request naming the task is its delivery too: Review waits until it is cited
    proof = "; ".join(parts)
    return proof, f"Pull request ready: {proof}"


def open_pulls(
    facts: TaskFacts, agent: Agent, said: str, problem: Callable[[dict[str, Any]], bool]
) -> tuple[str, str] | None:
    """The open pull requests of the task's own delivery that `problem` holds of, with the comment `said` names them
    in, else None. The head commit is in the evidence, so a push that fails or conflicts again is a new fact."""
    parts = []
    for url in facts.own_prs(agent):
        record = facts.record(url)
        if record is not None and record["state"] == "OPEN" and problem(record):
            parts.append(f"{record['repo']}#{record['number']} at {record['headRefOid'][:12]}")
    if not parts:
        return None
    proof = "; ".join(parts)
    return proof, f"{said}: {proof}."


def pr_checks_failed(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The open pull requests whose required checks failed, else None."""
    return open_pulls(
        facts,
        agent,
        "Pull request checks failed",
        lambda record: (
            checks_verdict(
                record["state"], record["checks"], record["headRefOid"], record["rollup"], record["requiredChecks"]
            )
            == "failing"
        ),
    )


def pr_failing(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The open pull requests whose required checks failed, with the question the task's reason ends in, else None."""
    failing = pr_checks_failed(facts, agent)
    return failing and (
        failing[0],
        attention_reason(
            failing[1],
            "its required checks fail on the pull request head",
            ("fix it on the task branch and redeliver", "rescope the task"),
            ATTENTION_QUESTION,
        ),
    )


def pr_draft(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The open pull requests that are drafts, else None."""
    return open_pulls(facts, agent, "Pull request is a draft", lambda record: record["isDraft"])


def pr_conflicting(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The open pull requests that conflict with their base, else None."""
    return open_pulls(
        facts, agent, "Pull request conflicts with its base", lambda record: record["mergeable"] == "CONFLICTING"
    )


def pr_unfinished(facts: TaskFacts, agent: Agent, alive: bool) -> tuple[str, str] | None:
    """The first of the failing, draft and conflicting facts that holds, once the task's holder is running (`alive`) or
    is not. A holder the probe cannot reach leaves the task where it is for the next pass."""
    held = pr_checks_failed(facts, agent) or pr_draft(facts, agent) or pr_conflicting(facts, agent)
    if held is None:
        return None
    running = facts.alive(agent["id"])
    if running is None or running != alive:
        return None
    if alive:
        return held[0], f"{held[1]} Sent back to its session."
    return held[0], attention_reason(
        f"{held[1]} No session holds it (cause bug TASK-15921)",
        "its holder ended with its pull request not green",
        RESTART_OR_RESCOPE,
        ATTENTION_QUESTION,
    )


def pr_unfinished_alive(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The not-green pull request of a task whose holding session is running."""
    return pr_unfinished(facts, agent, True)


def pr_unfinished_dead(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The not-green pull request of a task no running session holds."""
    return pr_unfinished(facts, agent, False)


def phase_resumed(facts: TaskFacts, agent: Agent) -> Held:
    """The time and comment of the newest step of a phase in `[sequences]` the task's session took after the task
    entered its lane: the session going back to work is the event that sends the task back."""
    if review_unchanged(facts, agent):
        return None
    since = entered(facts, agent)
    steps = [
        (at, phase)
        for phase in facts.phases()
        if (placed := facts.machine_task(phase, agent["id"])) and (at := resumed_at(phase, placed, since)) is not None
    ]
    if not steps:
        return None
    at, phase = max(steps)
    return at, f"Its session resumed the {phase} phase. Sent back to In Progress."


def review_unchanged(facts: TaskFacts, agent: Agent) -> bool:
    """Whether every own pull request is open, ready and at the head the task entered Review with: a session resuming
    a phase on it changes nothing a reviewer sees, so it stays in Review until a push gives it a new head."""
    seen = facts.memory(agent["id"]).get("reviewed") or {}
    urls = facts.own_prs(agent)
    return (
        bool(urls)
        and unready(facts, agent) is None
        and all(
            (record := facts.record(url)) and record["state"] == "OPEN" and seen.get(url) == record["headRefOid"]
            for url in urls
        )
    )


def resumed_at(phase: str, placed: dict[str, Any], entered: float) -> float | None:
    # A delivery run that began before the task entered its lane is the holder finishing the run that put it there,
    # so its steps never count: a run ends with its `DELIVER_FINISHED`, and only one that begins after `entered` is
    # work resuming.
    if phase != "deliver":
        return placed["active"] if placed["active"] > entered else None
    began: float | None = None
    newest = None
    for step in placed["trail"]:
        began = step["at"] if began is None else began
        if began > entered:
            newest = step["at"]
        if step["event"] == "DELIVER_FINISHED":
            began = None
    return newest


def operator_pushback(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The words of the operator's pushback when it is the task's newest comment: the move it causes, or the
    answer to it, is a newer comment, so a task that returns to its lane carries no old pushback. The comment of the
    move sends the words back to the holder."""
    if (texts := facts.comments(agent)) is None:
        facts.unsettled()
        return None
    newest = texts[-1].strip() if texts else ""
    if not newest.startswith(PUSHBACK):
        return None
    words = newest.removeprefix(PUSHBACK).strip()
    return newest, f"{SENT_BACK} {words}"


def _requested(marker: str) -> Callable[[TaskFacts, Agent], Held]:
    """The fact that the task's newest comment not written by the actor is a request `marker` opens: its words, the
    comment a move makes."""

    def requested(facts: TaskFacts, agent: Agent) -> Held:
        if (texts := facts.comments(agent)) is None:
            facts.unsettled()
            return None
        newest = next((text.strip() for text in reversed(texts) if not text.startswith(ACTOR_NOTES)), "")
        return (newest, newest.removeprefix(marker).strip()) if newest.startswith(marker) else None

    return requested


wait_requested = _requested(WAIT_REQUEST)
ask_requested = _requested(ASK_REQUEST)
_archive_comment = _requested(ARCHIVE_REQUEST)


def archive_requested(facts: TaskFacts, agent: Agent) -> Held:
    """The task's newest `ARCHIVE_REQUEST` comment, else at its session's settle the answer that chose archive to the
    closed-unmerged ask, so the choice archives whether or not the session wrote the request."""
    if (held := _archive_comment(facts, agent)) or not facts.settling(agent["id"]):
        return held
    if (closed := pr_closed_unmerged(facts, agent)) is None:
        return None
    if (texts := facts.comments(agent)) is None:
        return None
    answer = closed_answer(facts, agent, texts, closed[1])
    return (f"{ARCHIVE_REQUEST} {answer}", answer) if answer and ARCHIVE_ANSWER.match(answer) else None


freeze_requested = _requested(FREEZE_REQUEST)
unfreeze_requested = _requested(UNFREEZE_REQUEST)


def requested_lane(request: str) -> str:
    """The lane a `Move requested: <lane>. <words>` comment names."""
    return request.removeprefix(MOVE_REQUEST).partition(".")[0].strip()


def move_requested(facts: TaskFacts, agent: Agent) -> Held:
    """The operator's move request when it is the newest comment: the request, and the words after its lane, which the
    move records (a request with none is recorded as made at the operator's request)."""
    held = _requested(MOVE_REQUEST)(facts, agent)
    if held is None:
        return None
    return held[0], held[0].partition(".")[2].strip() or f"Moved to {requested_lane(held[0])} at the operator's request."


def deps_done(facts: TaskFacts, agent: Agent) -> Held:
    """The dependencies once every one is done and merged, an empty tuple when the task has none, and no Start
    Criteria gate it."""
    dependencies = tuple(agent["dependencies"])
    facts.pin_held(agent["id"], False)
    facts.held(agent["id"], False)
    if unmet(facts, agent) or criteria.authored(agent["description"]):
        return None
    if waiting := facts.waiting_on(agent):
        facts.pin_held(agent["id"], True)
        facts.note_hold(agent, (waiting,))
        return None
    if (reasons := held_by(facts, agent["id"])) is None:
        return None  # the board's hook is still running: its result derives the task again
    if reasons:
        facts.held(agent["id"], True)
        facts.note_hold(agent, reasons)
        return None
    comment = "Every dependency has merged."
    if ahead := early(facts, agent):
        comment = f"Stale dependency {', '.join(ahead)}: it stays open for criteria this task does not need. {comment}"
    return dependencies, comment


def deps_done_with_pr(facts: TaskFacts, agent: Agent) -> Held:
    """`deps_done` for a task that cites a ready or merged pull request, which a state returns to Review rather than Ready.

    A started task parked out of Review or Needs attention resumes In Progress instead (`deps_done_started`): its park
    asked for more work, so the pull request it cites is no reason to review it again."""
    if facts.started(agent["id"]) and facts.memory(agent["id"]).get("parked_out"):
        return None
    return deps_done(facts, agent) if pr_ready(facts, agent) else None


def held_by(facts: TaskFacts, name: str) -> tuple[str, ...] | None:
    """Why the board withholds the task's `deps_done`, a hold that raises holds it with that error; None while the
    board's hook still runs."""
    facts.hooked()
    return facts.holds(name)


def deadline(facts: TaskFacts, agent: Agent) -> tuple[float, str] | None:
    """When the task's service level expectation ends, in epoch seconds, and what it is counted from; None while the
    task is exempt (gated only on dependencies, each still In Progress or Review) or has no entry time.
    The SLE is the latest `expect_by` plus two days, else seven days from entering the lane."""
    if not (since := entered(facts, agent)):
        return None
    if dead(facts, agent):
        return since, "its wait can never end"
    if not criteria.authored(agent["description"]) and moving(facts, agent):
        return None
    dates = [stamp for stamp in map(epoch, criteria.expect_dates(agent["description"])) if stamp]
    if dates:
        return max(dates) + GRACE_DAYS * DAY_S, f"expect_by {stamp(max(dates))} plus {GRACE_DAYS} days"
    return since + SLE_DAYS * DAY_S, f"{SLE_DAYS} days from entering Waiting"


def moving(facts: TaskFacts, agent: Agent) -> bool:
    """Whether the task has open dependencies and each is In Progress or Review: work is under way on its gate."""
    roles = facts.roles
    open_ = [dependency for dependency in agent["dependencies"] if not cleared(facts, dependency)]
    return bool(open_) and all(
        (facts.task(dependency) or {}).get("state") in (roles.working, roles.review) for dependency in open_
    )


def overdue(facts: TaskFacts, agent: Agent) -> Held:
    """The deadline and the Needs attention question when the task is past its service level expectation."""
    due = deadline(facts, agent)
    now = facts.now()
    if not due or due[0] > now:
        return None
    if lost := dead(facts, agent):
        listed = ", ".join(agent["dependencies"]) or "none"
        return due[0], attention_reason(
            f"{'; '.join(lost)}, so nothing releases this task. Its dependencies ({listed}) are cleared with this move",
            "its wait can never end",
            ("re-park it on the right tasks or events", "close it"),
            "Re-park it on the right tasks or events, or close it?",
        )
    gate = [*unmet(facts, agent), *(each["id"] for each in criteria.authored(agent["description"]))]
    days = int((now - entered(facts, agent)) // DAY_S)
    return due[0], attention_reason(
        f"Waiting {days} days, past its service level expectation ({due[1]})",
        f"it is still gated on {', '.join(gate) or 'its wait'}",
        ("release it", "re-park it on a new wait", "close it"),
        "Release it, re-park it on a new wait, or close it?",
    )


def criteria_met(facts: TaskFacts, agent: Agent) -> Held:
    """The subjects heard when an event the task is parked on arrived and no dependency is open, which would hold it back."""
    heard = sorted(facts.heard(agent["id"]))
    if not heard or unmet(facts, agent):
        return None
    return tuple(heard), f"Event {', '.join(heard)} arrived."


def deps_unresolved(facts: TaskFacts, agent: Agent) -> Held:
    """The dependencies that are not done, when there are any. A task whose every pull request closed unmerged is
    held by `pr_closed_unmerged` instead: waiting on a dependency would move it back out of Needs attention."""
    open_ = unmet(facts, agent)
    return (open_, f"Not done: {', '.join(open_)}.") if open_ and not pr_closed_unmerged(facts, agent) else None


def owner_stale(facts: TaskFacts, agent: Agent) -> tuple[str, str] | None:
    """The green main SHA and the closing note when the task owns a failure (`owner_source`), main's Validate passed,
    and no open task lists it as a dependency; a red main names no signature, so it closes nothing."""
    if not facts.owns_failure(agent["id"]):
        return None
    waited_on = any(agent["id"] in (name.split("#")[0] for name in each["dependencies"]) for each in facts.open_tasks())
    sha = None if waited_on else facts.main_green()
    if not sha:
        return None
    return sha, f"Closed: main's Validate passed at {sha} and no open task waits on this failure."


def unmet(facts: TaskFacts, agent: Agent) -> tuple[str, ...]:
    """The dependencies that are neither done nor early: still open for what the task waits on."""
    ahead = early(facts, agent)
    return tuple(
        dependency
        for dependency in agent["dependencies"]
        if not cleared(facts, dependency) and dependency not in ahead and not owner_green(facts, dependency)
    )


def owner_green(facts: TaskFacts, dependency: str) -> bool:
    """Whether the dependency owns a failure (`owner_source`) and main's Validate passed: the failure no longer holds
    a task waiting on it, whatever lane the owner is in."""
    return facts.owns_failure(dependency) and bool(facts.main_green())


def early(facts: TaskFacts, agent: Agent, needs: Sequence[str] | None = None) -> tuple[str, ...]:
    """The open dependencies whose every criterion the task's record says it needs (`dependencyNeeds`, `TASK-N#K`)
    is checked: the fact the task waited on holds, whatever the dependency still has open. A dependency with no
    need names the whole task; a record the board cannot read names none. `needs` is a read the caller already holds."""
    open_ = [dependency for dependency in agent["dependencies"] if not cleared(facts, dependency)]
    if not open_:
        return ()
    needs = facts.dependency_needs(agent["id"]) if needs is None else needs
    wanted: dict[str, list[int]] = {}
    for task, number in map(need_of, needs):
        wanted.setdefault(task, []).append(number)
    return tuple(
        dependency for dependency in open_ if dependency in wanted and checked(facts, dependency, wanted[dependency])
    )


def checked(facts: TaskFacts, dependency: str, numbers: list[int]) -> bool:
    """Whether every criterion `numbers` names (1-based) of `dependency` is checked."""
    ticks = tuple(criterion["checked"] for criterion in (facts.task(dependency) or {}).get("criteria", ()))
    return all(0 < number <= len(ticks) and ticks[number - 1] for number in numbers)


def stale(facts: TaskFacts, agent: Agent) -> dict[str, list[str]]:
    """The record changes that drop the early dependencies and their needs, none when there are none."""
    needs = facts.dependency_needs(agent["id"])
    if not (ahead := early(facts, agent, needs)):
        return {}
    return {
        "dependencies": [dependency for dependency in agent["dependencies"] if dependency not in ahead],
        "dependencyNeeds": [need for need in needs if need_of(need)[0] not in ahead],
    }


def by_start(fact: Callable[[TaskFacts, Agent], Any], *, started: bool) -> Callable[[TaskFacts, Agent], Any]:
    """`fact` for the tasks a session was ever dispatched to or for the rest, so started work never falls through to
    Ready when its session ended and cleared the claim."""
    return lambda facts, agent: fact(facts, agent) if facts.started(agent["id"]) == started else None


#: Each fact kind a lane's `waits` name, and the function that answers it.
FACTS: dict[str, Callable[[TaskFacts, Agent], Held]] = {
    "pr_terminal": pr_terminal,
    "pr_merged": pr_merged,
    "pr_closed_unmerged": pr_closed_unmerged,
    "pr_closed_unmerged_complete": pr_closed_unmerged_complete,
    "pr_merged_unfinished": pr_merged_unfinished,
    "pr_ready": pr_ready,
    "criteria_checked": criteria_checked,
    "pr_failing": pr_failing,
    "pr_draft": pr_draft,
    "pr_conflicting": pr_conflicting,
    "pr_unfinished_alive": pr_unfinished_alive,
    "pr_unfinished_dead": pr_unfinished_dead,
    "phase_resumed": phase_resumed,
    "operator_pushback": operator_pushback,
    "wait_requested": wait_requested,
    "ask_requested": ask_requested,
    "archive_requested": archive_requested,
    "freeze_requested": freeze_requested,
    "unfreeze_requested": unfreeze_requested,
    "move_requested": move_requested,
    "deps_done": by_start(deps_done, started=False),
    "deps_done_with_pr": deps_done_with_pr,
    "deps_done_started": by_start(deps_done, started=True),
    "deps_unresolved": deps_unresolved,
    "criteria_met": by_start(criteria_met, started=False),
    "criteria_met_started": by_start(criteria_met, started=True),
    "owner_stale": owner_stale,
    "overdue": overdue,
}
