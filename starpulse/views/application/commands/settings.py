"""The settings a page puts: the history window, the scheduler's admission and Admin's display and theme."""

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from starpulse.board.adapters.display_settings import DisplaySettings
from starpulse.harness_telemetry.adapters.outbound.harness_settings import HarnessSettings
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.contracts.api.dto.admin import Display, Theme
from starpulse.contracts.api.dto.requests import (
    AdminRequest,
    HarnessesRequest,
    SchedulerRequest,
    WindowRequest,
)
from starpulse.harness_telemetry.model.harnesses import HarnessError, parse_harnesses
from starpulse.views.application.commands.guard import lan_refusal, on_lan, with_request

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.scheduler.adapters.remote import Remote
    from starpulse.scheduler.adapters.runtime import Runtime

logger = logging.getLogger(__name__)


@with_request(WindowRequest, "The history window")
def _set_window(request: WindowRequest, window: HistoryWindow) -> tuple[int, dict[str, Any]]:
    try:
        window.set(request.hours)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, window.state()


def history_window(source: str, method: str, raw: bytes, window: HistoryWindow) -> tuple[int, dict[str, Any]]:
    """Read (`GET`), set (`PUT {"hours": N}`) or reset (`DELETE`) the shared history window for a browser at `source`:
    the HTTP status and JSON body, which is the window's state, or the refusal."""
    if method == "PUT":
        return _set_window(source, raw, window)
    if not on_lan(source):
        return lan_refusal("The history window")
    if method == "DELETE":
        window.reset()
    return 200, window.state()


_ADMIN_USAGE = (
    'admin takes {"enabled": true|false}, {"harness": "<name>"} and/or '
    '{"quietHours": {"start", "end", "timezone"}|null} and/or {"sessionCap": <whole number above zero>|null} and/or '
    '{"cpuLimit": <percent above 0, at most 100>|null} and/or {"memoryLimit": <percent above 0, at most 100>|null} and/or '
    '{"display": {"scale", "motion", "view", "density", "clock"}} and/or {"theme": {"pack", "bg", "packs", "bgs"}}'
)
_LIMIT_FIELDS = {"cpuLimit": "cpu", "memoryLimit": "memory"}


def _set_scheduler(request: SchedulerRequest, runtime: Runtime | Remote) -> tuple[int, dict[str, Any]] | None:
    named = request.model_fields_set
    try:  # the request model has refused every other bad value, so only a quiet-hours window can fail here, first
        if "quietHours" in named:
            quiet = request.quietHours
            runtime.set_quiet_hours(None if quiet is None else quiet.model_dump())
        if "harness" in named:
            runtime.set_harness(request.harness)
        if "sessionCap" in named:
            runtime.set_session_cap(request.sessionCap)
        if limits := {name: getattr(request, field) for field, name in _LIMIT_FIELDS.items() if field in named}:
            runtime.set_limits(limits)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if request.enabled is not None:
        runtime.set_enabled(request.enabled)
    return None


_NAMED_VALUES = ("enabled", "display", "theme")


def _kept(store: DisplaySettings) -> tuple[Display, Theme]:
    kept = store.read()

    def one[M: Display | Theme](model: type[M]) -> M:
        try:
            return model.model_validate(kept.get(model.__name__.lower(), {}))
        except ValidationError as exc:  # fail closed: a value the models refuse is no choice made
            logger.warning("admin settings: kept %s is invalid: %s", model.__name__.lower(), exc)
            return model()

    return one(Display), one(Theme)


def _state(runtime: Runtime | Remote, store: DisplaySettings) -> dict[str, Any]:
    display, theme = _kept(store)
    return {**runtime.served_status(), "display": display.model_dump(), "theme": theme.model_dump()}


@with_request(AdminRequest, "Admin's settings")
def _put_admin(request: AdminRequest, runtime: Runtime | Remote, store: DisplaySettings) -> tuple[int, dict[str, Any]]:
    named = request.model_fields_set
    if not named or any(getattr(request, field) is None for field in _NAMED_VALUES if field in named):
        return 400, {"error": _ADMIN_USAGE}
    if refusal := _set_scheduler(request, runtime):
        return refusal
    if "display" in named or "theme" in named:
        display, theme = _kept(store)
        if request.display is not None:
            display = display.model_copy(update=request.display.model_dump(exclude_none=True))
        store.write({"display": display.model_dump(), "theme": (request.theme or theme).model_dump()})
    return 200, _state(runtime, store)


def admin(
    source: str, method: str, raw: bytes, runtime: Runtime | Remote | None, store: DisplaySettings | None
) -> tuple[int, dict[str, Any]]:
    """Read (`GET`) the scheduler's state with the display and theme every device shares, or set (`PUT`) any of the
    scheduler's settings (`scheduler`'s body), `{"display": {...}}` with only the fields that change and/or
    `{"theme": {...}}` whole, for a browser at `source`.

    A read answers any address; a write answers only loopback and RFC 1918. A body with anything wrong changes nothing.
    """
    if runtime is None or store is None:
        return 404, {"error": "this instance runs no scheduler" if runtime is None else "this instance keeps no display settings"}
    if method == "PUT":
        return _put_admin(source, raw, runtime, store)
    return 200, _state(runtime, store)


_HARNESSES_USAGE = 'harnesses takes {"tiers": [<name>, ...]} and/or {"harnesses": [<harness as GET answers it>, ...]}'


@with_request(HarnessesRequest, "The harness config")
def put_harnesses(request: HarnessesRequest, store: HarnessSettings) -> tuple[int, dict[str, Any]]:
    """Set the tiers and/or each named harness over the kept config: the HTTP status and the whole config it keeps,
    or the refusal of a body that would leave a harness the harness rules refuse, which changes nothing."""
    if request.tiers is None and request.harnesses is None:
        return 400, {"error": _HARNESSES_USAGE}
    kept = store.current().as_toml()
    if request.tiers is not None:
        kept["tiers"] = request.tiers
    for harness in request.harnesses or ():
        body = harness.model_dump(exclude_none=True)
        kept["harnesses"][body.pop("name")] = body
    try:
        harnesses = parse_harnesses(kept)
    except HarnessError as exc:
        return 400, {"error": str(exc)}
    store.write(harnesses)
    return 200, harnesses.as_json()
