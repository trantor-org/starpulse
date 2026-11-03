"""The GitHub REST API transport that Delivery's pull reader and Runs' GitHub Actions adapter share: a signed-in
`Transport`, its `get` read, the `GitHubError` of a read that fails, and `repo_of` for a repository's `owner/name`."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable

#: `(method, path, body)` to the GitHub REST API, answered with the HTTP status and the decoded body.
Transport = Callable[[str, str, dict | None], tuple[int, dict]]


class GitHubError(OSError):
    """GitHub answered a read with a status other than 200."""

    def __init__(self, status: int, path: str) -> None:
        super().__init__(f"GitHub answered HTTP {status} for {path}")
        self.status = status


def get(transport: Transport, path: str) -> dict:
    status, body = transport("GET", path, None)
    if status != 200:
        raise GitHubError(status, path)
    return body


def connect(token: str | None, timeout: float = 30.0) -> Transport:  # pragma: no mutate block — HTTP boundary
    """A transport to the GitHub API (`GITHUB_API_URL`, else api.github.com), signed in with `token` when there is one."""
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"} | (
        {"Authorization": f"Bearer {token}"} if token else {}
    )

    def send(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        request = urllib.request.Request(
            base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                decoded = json.loads(raw) if raw else {}
                if isinstance(decoded, list):  # a list endpoint's array comes back as `{"items": [...]}`
                    decoded = {"items": decoded}
                return response.status, decoded if isinstance(decoded, dict) else {}
        except urllib.error.HTTPError as exc:
            return exc.code, {}
        except json.JSONDecodeError as exc:
            raise OSError(f"GitHub returned malformed JSON: {exc}") from exc

    return send


_REPO = re.compile(r"(?:https://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?")


def repo_of(url: str) -> str:
    """`owner/name` of the repository `url` names, as `owner/name` or its github.com address."""
    match = _REPO.fullmatch(url)
    if match is None:
        raise ValueError(f"{url!r} is not a GitHub repository: use owner/name or https://github.com/owner/name")
    return f"{match[1]}/{match[2]}"
