"""The missed loads and trace clusters."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.api._base import _Api


class CaseRef(_Api):
    """One session's work on one task (`task` None: a branch that names none)."""

    harness: str
    session: str
    task: str | None
    last_at: float


class MissedSkill(_Api):
    """A declared skill: the cases that performed what should load it, and those that did not load it."""

    skill: str
    performed: int
    missed: int
    listed: list[CaseRef] = Field(description="The `list` most recent missed cases, newest first.")


class MissedLoads(_Api):
    """`GET /api/analytics/missed-loads`: per declared skill, the cases that ran its trigger without loading it."""

    now: float
    window_s: float
    skills: list[MissedSkill]


class ClusterSkill(_Api):
    skill: str
    cases: int


class ClusterMissed(_Api):
    skill: str
    performed: int
    missed: int


class ClusterMedoid(_Api):
    """The case nearest every other by normalized LCS distance between traces, and the cluster's usual spread."""

    case: CaseRef
    median_distance: float
    trace: list[str]


class ClusterOutlier(_Api):
    """A case far from the medoid: `deletions` are the medoid's activities it lacks, `insertions` its own extra."""

    case: CaseRef
    distance: float
    deletions: list[str]
    insertions: list[str]


class TraceCluster(_Api):
    """Cases that did the same distinctive work, and the skills that covered it."""

    key: str = Field(description="A stable id: the digest of the sorted descriptors.")
    sessions: int
    cases: int
    tasks: list[str]
    first_at: float
    last_at: float
    kinds: dict[str, int]
    descriptors: list[str] = Field(
        description="The features with the most weight across the cases: `a:` activity, `r:` area read, `w:` area written."
    )
    skills: list[ClusterSkill] = Field(description="The three most loaded skills, less the lifecycle skills.")
    uncovered: int = Field(description="Cases that loaded no skill beyond the lifecycle skills.")
    sample_sessions: list[str]
    sample_tasks: list[str]
    titles: list[str]
    missed_loads: list[ClusterMissed]
    medoid: ClusterMedoid | None = Field(description="Null unless `outliers` was asked for.")
    outliers: list[ClusterOutlier]


class TraceClusters(_Api):
    """`GET /api/analytics/trace-clusters`: recurring work, ranked by distinct sessions."""

    now: float
    window_s: float
    threshold: float
    min_sessions: int
    cases: int = Field(description="Cases with a trace in the window.")
    clustered: int = Field(description="Cases that joined a cluster, whatever its size.")
    clusters: list[TraceCluster]
