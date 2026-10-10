"""`POST /api/pulls/refresh`: one pull request's read, asked for by a producer that just saw it close.

The body is `{"repo": "<owner>/<name>", "number": <pull request number>}` with `Authorization: Bearer <token>`, the
token the config's `refresh_token_env` names. The PR store's thread reads that pull request alone, as soon as it is
asked, and publishes it as a refresh does; the 60 s refresh stays the fallback for a request that is lost.

The answers: 202 when the request is queued; 401 for a missing or wrong token; 403 for a repository the instance does
not track; 400 for a body that is not a repository and a pull request number. A refusal queues nothing.
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Callable
from typing import Any

#: The largest body accepted: a request is a repository name and a number.
MAX_BODY = 1024
_REPO = re.compile(r"[\w.-]+/[\w.-]+")


class PullRefresh:
    """Answers one `POST /api/pulls/refresh`: `(authorization header, body)` to `(status, JSON body)`.

    `request` queues the read and says whether the repository is one the instance tracks."""

    def __init__(self, token: str, request: Callable[[str, int], bool]) -> None:
        self._token = token
        self._request = request

    def __call__(self, authorization: str | None, raw: bytes) -> tuple[int, dict[str, Any]]:
        scheme, _, presented = (authorization or "").partition(" ")
        if not (
            scheme.lower() == "bearer" and presented and hmac.compare_digest(self._token.encode(), presented.encode())
        ):
            return 401, {"error": "a valid token is required: Authorization: Bearer <token>"}
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        fields = body if isinstance(body, dict) else {}
        repo, number = fields.get("repo"), fields.get("number")
        if not (
            isinstance(repo, str)
            and _REPO.fullmatch(repo)
            and isinstance(number, int)
            and not isinstance(number, bool)
            and number > 0
        ):
            return 400, {"error": 'the body must be {"repo": "<owner>/<name>", "number": <pull request number>}'}
        if not self._request(repo, number):
            return 403, {"error": f"this instance tracks no pull requests of {repo}"}
        return 202, {"accepted": True}
