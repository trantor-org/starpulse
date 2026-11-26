"""A machine document and the board policy's table rows, as a machine write takes them: `machine.schema.json` field by
field, and the policy tables' columns."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, JsonValue, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from starpulse.contracts.api._base import _Request

_NAME = r"^[A-Za-z][A-Za-z0-9_-]*$"
_EVENT = r"^[A-Za-z][A-Za-z0-9_]*$"
_IDENTIFIER = r"^[a-z][a-z0-9_]*$"
_RESERVED = ("event", "event_data", "machine", "model", "source", "state", "target", "transition")

def _unreserved(name: str) -> str:
    if name in _RESERVED:
        raise ValueError(f"{name} is a name the event carries itself")
    return name


Identifier = Annotated[str, Field(pattern=_IDENTIFIER)]
EventName = Annotated[str, Field(pattern=_EVENT)]
Text = Annotated[str, Field(min_length=1)]
Scalar = StrictBool | StrictInt | StrictFloat | StrictStr
#: A field name of the triggering event a guard matches, which is none of the names the event carries itself.
_Field = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"), AfterValidator(_unreserved)]


class EventMatch(_Request):
    """How one event field is matched: exactly one of `equals`, `in` and `exists`."""

    equals: Scalar | None = None
    in_: list[Scalar] | None = Field(None, alias="in", min_length=1)
    exists: StrictBool | None = None

    @model_validator(mode="after")
    def _one(self) -> EventMatch:
        if len(self.model_fields_set) != 1:
            raise ValueError("a match names exactly one of equals, in and exists")
        return self


class MachineGuard(_Request):
    when: dict[_Field, EventMatch] = Field(min_length=1)


class MachineCite(_Request):
    skill: Text
    quote: Text


class MachineTransition(_Request):
    from_: str | Annotated[list[str], Field(min_length=1)] = Field(alias="from")
    to: str
    if_: MachineGuard | None = Field(None, alias="if")
    unless: MachineGuard | None = None
    cite: MachineCite | None = None

    @model_validator(mode="after")
    def _from_once(self) -> MachineTransition:
        if isinstance(self.from_, list) and len(set(self.from_)) != len(self.from_):
            raise ValueError("from names a state once")
        return self


class MachineState(_Request):
    initial: StrictBool | None = None
    final: StrictBool | None = None
    label: Text | None = None
    aliases: list[Text] | None = None
    priority: Annotated[StrictInt, Field(ge=0)] | None = None
    role: Literal["resting", "waiting_on_fact", "waiting_on_person"] | None = None


class MachineWriter(_Request):
    actor: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_./-]+)?$")]
    trigger: Text


class MachineSubmachine(_Request):
    state: Identifier
    machine: Text
    exits: dict[Identifier, EventName]
    routes: dict[Identifier, EventName] | None = None
    when: str | None = None
    skill: Text | None = None


class MachineLaunch(_Request):
    skill: Text
    machine: Text | None = None


class MachineCue(_Request):
    event: EventName
    dag: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+/[A-Za-z0-9_./-]+$")]
    on: Text
    resolves: Literal["forced", "next"]
    grace: Annotated[StrictInt, Field(ge=1)] | None = None


class MachineNext(_Request):
    kind: Literal["skill", "operation"]
    name: Text


class MachineDefinition(_Request):
    """A machine document: its states, the events that move a task between them, and what it declares around them."""

    name: Annotated[str, Field(pattern=_NAME)]
    source: Text | None = None
    type: Literal["machine", "phase machine", "sub-machine"] | None = None
    parents: list[Text] | None = None
    states: dict[Identifier, MachineState] = Field(min_length=1)
    events: dict[EventName, Annotated[list[MachineTransition], Field(min_length=1)]] = Field(min_length=1)
    migrations: dict[Identifier, Identifier] | None = None
    bindings: dict[str, str] | None = None
    writers: dict[EventName, Annotated[list[MachineWriter], Field(min_length=1)]] | None = None
    cues: Annotated[list[MachineCue], Field(min_length=1)] | None = None
    tiers: Annotated[list[Annotated[list[Identifier], Field(min_length=1)]], Field(min_length=1)] | None = None
    main_line: Annotated[list[Identifier], Field(min_length=1)] | None = None
    rests: Annotated[list[Identifier], Field(min_length=1)] | None = None
    submachines: Annotated[list[MachineSubmachine], Field(min_length=1)] | None = None
    next: MachineNext | None = None
    launches: dict[str, MachineLaunch] | None = Field(None, min_length=1)

    def document(self) -> dict[str, JsonValue]:
        """The document as written: the keys the caller named, under their names in the file."""
        return self.model_dump(by_alias=True, exclude_unset=True)


class PolicyLane(_Request):
    name: str
    role: str | None
    position: int
    skill: str | None = None
    label: str | None = None


class PolicyRoute(_Request):
    event: str
    source: str
    target: str
    condition: dict[str, JsonValue] | None = None


class PolicyExit(_Request):
    event: str
    actor: str
    trigger: str


class PolicyWatch(_Request):
    lane: str
    fact: str
    event: str
    position: int


class PolicyRule(_Request):
    position: int
    on: dict[str, JsonValue]
    require: dict[str, JsonValue]
    reason: str
    skill: str
    unless_actor: list[str]


class PolicyVocabulary(_Request):
    name: str
    value: str
    position: int


class PolicyProfile(_Request):
    kind: str
    size: int
    profile: str


class PolicyTool(_Request):
    lane: str
    tool: str


class PolicyRows(_Request):
    """The table rows of the whole board policy; a table left out holds no row."""

    lanes: list[PolicyLane] = []
    routes: list[PolicyRoute] = []
    exits: list[PolicyExit] = []
    watches: list[PolicyWatch] = []
    rules: list[PolicyRule] = []
    vocabularies: list[PolicyVocabulary] = []
    profiles: list[PolicyProfile] = []
    tools: list[PolicyTool] = []
