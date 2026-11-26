"""`/api/admin`: the scheduler's status with the display and theme choices every device shares."""

from typing import Annotated, Literal

from pydantic import Field, JsonValue, StrictInt

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.scheduler import SchedulerStatus

Scale = Annotated[
    StrictInt,
    Field(ge=85, le=150, multiple_of=5, description="The font size in percent of the design size, in steps of 5."),
]
OpensOn = Literal["constellation", "kanban"]
Density = Literal["comfortable", "compact"]
Clock = Literal["24", "12"]


class Display(_Api):
    """How every device draws the page; a field left out of a write keeps its value."""

    scale: Scale = 100
    motion: bool = Field(default=True, description="Off stills CSS animation and transitions and slows the Star Map's frame loop.")
    view: OpensOn = Field(default="constellation", description="The view an address with no `view` parameter opens.")
    density: Density = "comfortable"
    clock: Clock = "24"


class PackSource(_Api):
    label: str


class Pack(_Api):
    """A color pack as the page builds it: `c` the role colors, `r` each role's derivation (a color, or a mix of two derivations), `x` any extra tokens."""

    name: str
    vibe: str | None = None
    src: PackSource | None = None
    c: dict[str, str]
    r: dict[str, JsonValue]
    x: dict[str, str] | None = None


class SavedPack(_Api):
    """A color pack an operator imported."""

    id: str
    pack: Pack


class SavedBg(_Api):
    """A background an operator imported; `n` is its neutral colors by name."""

    id: str
    name: str
    n: dict[str, str]


class Theme(_Api):
    """The color pack and background every device draws in, built in or imported; a write replaces the whole theme."""

    pack: str = Field(default="starpulse", description="The id of a built-in pack or of one in `packs`.")
    bg: str = Field(default="slate", description="The id of the built-in background or of one in `bgs`.")
    packs: list[SavedPack] = Field(default_factory=list)
    bgs: list[SavedBg] = Field(default_factory=list)


class AdminState(SchedulerStatus):
    """Admin's settings in one answer: the scheduler's status, then the display and theme choices."""

    display: Display
    theme: Theme
    position: int = Field(
        description="The stream position the state was read at: a `schedulerChanges` subscription from it misses no status change."
    )
