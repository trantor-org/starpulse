"""The session-start service the Kanban view's Start session reaches: `POST <url>/start/TASK-N`.

The service opens a Remote Control session on the task's assignee profile and
answers `{"task", "url"}` once the session has its bridge, waiting up to a minute for it; a 502 or 504 says why
it could not. Its address is the config's `session_start_url`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from starpulse.contracts import StartFailedError

#: Seconds to wait for an answer: longer than the service's own minute for the bridge.
_TIMEOUT_S = 75.0


def starter(url: str | None) -> Callable[[str], str] | None:
    """Start a task's session at the service `url` names and return the session's URL; None without an address."""
    if url is None:
        return None
    base = url.rstrip("/")

    def start(task: str) -> str:
        request = urllib.request.Request(f"{base}/start/{task}", method="POST")
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
