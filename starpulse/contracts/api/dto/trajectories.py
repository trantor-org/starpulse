"""`/api/level/trajectories`: trajectories and forecasts."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.api._base import _Api


class Variant(_Api):
    path: list[str]
    count: int
    share: float


class Norm(_Api):
    path: list[str]
    count: int


class Outlier(_Api):
    source: str
    task: str
    path: list[str]
    distance: int


class ChainState(_Api):
    expected_days: float
    p_goal: float


class Bottleneck(_Api):
    state: str
    path_days: float


class RunGate(_Api):
    gate: str
    crossed: bool
    mandatory: bool
    dominators: list[str]
    post_dominators: list[str]
    witness: list[str] | None


class RunLoop(_Api):
    """One back-edge a run took: its trips and the days they took, from the target's previous visit to each return."""

    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str
    trips: int
    days: float


class TrajectoryRun(_Api):
    source: str
    task: str
    path: list[str]
    reached_goal: bool
    back_edges: int
    sccs: int
    loops: list[RunLoop]
    gates: list[RunGate]


class GateWitness(_Api):
    task: str
    path: list[str]


class GateSummary(_Api):
    gate: str
    runs: int
    crossed: int
    mandatory: int
    bypassed: int
    bypassable: bool
    witness: GateWitness | None


class LevelLoop(_Api):
    """One back-edge across the runs that took it, summed from the runs' own figures."""

    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str
    runs: int
    trips: int
    days: float


class Forecast(_Api):
    """One run still going: where it is, its loops so far, and from its state's row the chance of each terminal and
    of the goal and its expected days to finish, with `n`, the times that row was seen leave. Null with no row."""

    source: str
    task: str
    state: str
    loops: int
    since: float
    p: dict[str, float] | None
    p_goal: float | None
    expected_days: float | None
    n: int
    pooled: bool


class Decile(_Api):
    """One decile of forecast chance of the goal on the held-out runs: its forecasts' mean against the share of
    their runs that reached the goal, null when it holds none."""

    low: float
    high: float
    n: int
    runs: int
    predicted: float | None
    observed: float | None


class Calibration(_Api):
    """The forecast scored on the latest fifth of the ended runs against a chain fitted on the others."""

    fit: int
    held_out: int
    predictions: int
    unscored: int
    deciles: list[Decile]
    calibrated: bool | None


class Trajectories(_Api):
    """`GET /api/level/trajectories`: the paths of the runs that ended in a terminal over a window."""

    now: float
    window_s: float
    history_s: float
    machine: str
    goal: str
    ended: int
    variants: list[Variant]
    norm: Norm | None
    outliers: list[Outlier]
    chain: dict[str, ChainState]
    betweenness: dict[str, float]
    bottleneck: Bottleneck | None
    gates: list[GateSummary]
    loops: list[LevelLoop]
    runs: list[TrajectoryRun]
    forecast: list[Forecast]
    calibration: Calibration
