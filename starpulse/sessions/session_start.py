"""The session-start service the Kanban view's Start session reaches: `POST <url>/start/TASK-N`.

The service opens a session on the task's assignee profile for the named harness and mode, and
answers `{"task", "url"}` once the session has its bridge, waiting up to a minute for it; a 502 or 504 says why
it could not. Its address is the config's `session_start_url`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from starpulse.contracts.adapters import StartFailedError

#: Seconds to wait for an answer: longer than the service's own minute for the bridge.
_TIMEOUT_S = 75.0


def starter(url: str | None, by: str | None = None) -> Callable[..., str] | None:
    """Start a task's session at the service `url` names and return the session's URL; None without an address.

    With `by`, each request names who starts the session (`?by=scheduler`), so the service can brief an unattended
    session differently from one an operator opened. Every start names `harness` and `mode` (default `interactive`)
    so the service can dispatch; an operator's start carries no `by` marker.
    """
    if url is None:
        return None
    base = url.rstrip("/")

    def start(
        task: str, *, harness: str = "claude", mode: str = "interactive", verb: str = "Start", profile: str | None = None
    ) -> str:
        params: dict[str, str] = {"harness": harness, "mode": mode}
        if by:
            params["by"] = by
        if verb != "Start":  # a verify session names its prompt verb and the profile it runs on
            params["verb"] = verb
        if profile:
            params["profile"] = profile
        query = f"?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(f"{base}/start/{task}{query}", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                session = json.load(response).get("url")
        except urllib.error.HTTPError as exc:
            raise StartFailedError(exc.read().decode(errors="replace").strip() or str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise StartFailedError(f"the session-start service at {base} did not answer: {exc}") from exc
        if not isinstance(session, str) or not session:
            raise StartFailedError(f"the session-start service at {base} named no session for {task}")
        return session

    return start
