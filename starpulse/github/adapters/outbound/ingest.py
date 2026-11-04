"""`HttpIngest`: posts one CloudEvent to the server's `/api/machine-events` as the `github` producer."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

__all__ = ["HttpIngest"]

_PATH = "/api/machine-events"
_TIMEOUT_S = 10.0


class HttpIngest:
    """Answers the HTTP status the ingest gave an event, or 0 when it was not reached."""

    def __init__(self, base_url: str, token: str, timeout: float = _TIMEOUT_S) -> None:
        self._url, self._token, self._timeout = base_url.rstrip("/") + _PATH, token, timeout

    def post(self, event: dict[str, Any]) -> int:
        request = urllib.request.Request(  # noqa: S310 - the configured server URL, http or https
            self._url,
            json.dumps(event).encode(),
            {"Content-Type": "application/cloudevents+json", "Authorization": f"Bearer {self._token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as answer:  # noqa: S310
                return answer.status
        except urllib.error.HTTPError as refused:
            return refused.code
        except OSError:
            return 0
