"""The settings a page puts: the history window and the scheduler's admission."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.contracts.api.dto.requests import (
    SchedulerRequest,
    WindowRequest,
)
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


_SCHEDULER_USAGE = (
    'the scheduler takes {"enabled": true|false}, {"harness": "<name>"} and/or '
    '{"quietHours": {"start", "end", "timezone"}|null}'
)


@with_request(SchedulerRequest, "The scheduler switch")
def _put_scheduler(request: SchedulerRequest, runtime: Runtime | Remote) -> tuple[int, dict[str, Any]]:
    named = request.model_fields_set
    if not named or ("enabled" in named and request.enabled is None):
        return 400, {"error": _SCHEDULER_USAGE}
    try:
        if "harness" in named:
            runtime.set_harness(request.harness)
        if "quietHours" in named:
            quiet = request.quietHours
            runtime.set_quiet_hours(None if quiet is None else quiet.model_dump())
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if request.enabled is not None:
        runtime.set_enabled(request.enabled)
    return 200, runtime.served_status()


def scheduler(source: str, method: str, raw: bytes, runtime: Runtime | Remote | None) -> tuple[int, dict[str, Any]]:
    """Read (`GET`) whether the scheduler admits tasks, which harness it starts on, its quiet hours and each capacity
    dimension's use against its limit, or set (`PUT {"enabled": bool}`, `PUT {"harness": "<name>"}`,
    `PUT {"quietHours": {...} | null}`, or any combination) those settings, for a browser at `source`.

    Settings are kept in the store the scheduler reads, so a PUT takes effect at the next admission and survives a
    restart. A read answers any address, as every read does; a write answers only loopback and RFC 1918. A body with
    anything wrong changes nothing.
    """
    if runtime is None:
        return 404, {"error": "this instance runs no scheduler"}
    if method == "PUT":
        return _put_scheduler(source, raw, runtime)
    return 200, runtime.served_status()
