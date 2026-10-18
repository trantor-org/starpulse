"""`/api/level`: the level a harness is held to."""

from __future__ import annotations

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.health import HealthThroughput


class LevelTerminal(_Api):
    id: str
    role: str


class LevelOrbitConfig(_Api):
    suns: str
    working: list[str]


class LevelFacet(_Api):
    id: str
    label: str


class LevelActivity(_Api):
    measure: str
    pace: str


class LevelConfig(_Api):
    """What the page needs of the level's config to draw it."""

    title: str
    subject: str
    runs: str
    gates: list[str]
    terminals: list[LevelTerminal]
    orbit: LevelOrbitConfig
    facets: list[LevelFacet]
    activity: LevelActivity


class LevelWip(_Api):
    count: int
    states: dict[str, int]


class LevelStay(_Api):
    id: str
    visits: int
    task_s: float
    mean_s: float | None


class AgingRun(_Api):
    source: str
    task: str
    state: str
    age_s: float
    over: bool


class LevelAging(_Api):
    threshold_s: float | None
    runs: list[AgingRun]


class OrbitTerminal(_Api):
    ended: int


class OrbitWorking(_Api):
    task_s: float


class LevelOrbit(_Api):
    suns: str
    terminals: dict[str, OrbitTerminal]
    working: dict[str, OrbitWorking]


class Arrival(_Api):
    source: str
    state: str
    at: float


class SourceDwell(_Api):
    visits: int
    task_s: float
    mean_s: float | None


class LevelSource(_Api):
    id: str
    shared: bool
    wip: int
    ended: dict[str, int]
    terminal_share: dict[str, float]
    dwell: dict[str, SourceDwell]
    time_share: dict[str, float]


class Level(_Api):
    """`GET /api/level`: the level's flow numbers over a window."""

    now: float
    window_s: float
    history_s: float
    machine: str
    goal: str
    level: LevelConfig
    wip: LevelWip
    throughput: HealthThroughput
    time_in_state: list[LevelStay]
    aging: LevelAging
    orbit: LevelOrbit
    arrivals: list[Arrival]
    sources: list[LevelSource]
