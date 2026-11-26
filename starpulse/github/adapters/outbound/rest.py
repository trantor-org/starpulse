"""The GitHub REST API transport that Delivery's pull reader and Runs' GitHub Actions adapter share: a signed-in
`Transport`, its `get` read, the `GitHubError` of a read that fails, and `repo_of` for a repository's `owner/name`."""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: `(method, path, body)` to the GitHub REST API, answered with the HTTP status and the decoded body.
Transport = Callable[[str, str, dict | None], tuple[int, dict]]


@dataclass(frozen=True)
class Reply:
    """An answer to a conditional request: the status (304 when the ETag still holds), the decoded body, the ETag and the
    path of the next page of a list."""

    status: int
    body: dict
    etag: str | None = None
    next: str | None = None


#: `(method, path, etag)` to the GitHub REST API: `etag` is sent as `If-None-Match`, and a 304 spends no rate limit.
Client = Callable[[str, str, str | None], Reply]


class GitHubError(OSError):
    """GitHub answered a read with a status other than 200."""

    def __init__(self, status: int, path: str, message: str | None = None) -> None:
        super().__init__(message or f"GitHub answered HTTP {status} for {path}")
        self.status = status


class RateLimited(GitHubError):
    """GitHub refused a read because the quota is spent; `until` is the epoch second it resets."""

    def __init__(self, status: int, path: str, until: float) -> None:
        reset = time.strftime("%H:%M:%S UTC", time.gmtime(until))
        super().__init__(status, path, f"GitHub rate limit spent until {reset} (HTTP {status} for {path})")
        self.until = until


def _reset_of(headers: Any, now: float) -> float | None:
    """The epoch second a 403 or 429 says the quota is back, or None when the refusal is not a rate limit."""
    if (after := headers.get("Retry-After")) and after.isdigit():
        return now + int(after)
    if headers.get("X-RateLimit-Remaining") == "0" and (reset := headers.get("X-RateLimit-Reset", "")).isdigit():
        return float(reset)
    return None


def get(transport: Transport, path: str) -> dict:
    status, body = transport("GET", path, None)
    if status != 200:
        raise GitHubError(status, path)
    return body


_ID = re.compile(r"/(\d+)(?=/|$)")
_SHA = re.compile(r"/[0-9a-f]{7,40}(?=/|$)")
_TAIL = re.compile(r"(/(?:contents|rules/branches))/.+")


def endpoint_of(path: str) -> str:
    """The shape of a GitHub REST `path`: the query dropped and each repository, organisation, number, commit and
    free-form tail named by its kind, so a count per endpoint stays bounded."""
    shape = path.partition("?")[0]
    shape = re.sub(r"^/repos/[^/]+/[^/]+", "/repos/{repo}", shape)
    shape = re.sub(r"^/orgs/[^/]+", "/orgs/{org}", shape)
    shape = _TAIL.sub(r"\1/{path}", shape)
    shape = re.sub(r"/[^/]*\.\.\.[^/]*(?=/|$)", "/{range}", shape)
    return _SHA.sub("/{sha}", _ID.sub("/{n}", shape))


def _open(request: urllib.request.Request, path: str, timeout: float, caller: str) -> Any:
    """`urlopen`, logging the call as one `github-rest` line, as the gh shim logs a `gh-call`: an hour's count per caller
    and endpoint is a Loki `count_over_time` over those lines. A 304 counts, though it spends no rate limit."""
    status: int | str = "error"
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
        status = response.status
        return response
    except urllib.error.HTTPError as exc:
        status = exc.code
        raise
    finally:
        logger.info(
            "github-rest caller=%s method=%s endpoint=%s status=%s",
            caller,
            request.get_method(),
            endpoint_of(path),
            status,
        )


_MERGEABLE = {True: "MERGEABLE", False: "CONFLICTING"}


#: GitHub computes a pull request's mergeability on the first read after a push and answers null until it finishes, so a
#: read asks `_MERGEABLE_READS` times, `_MERGEABLE_WAIT` seconds apart.
_MERGEABLE_READS, _MERGEABLE_WAIT = 3, 1.0


def pull_mergeable(repo: str, number: int, timeout: float) -> str | None:
    """GitHub's answer now whether the pull request merges (`MERGEABLE` or `CONFLICTING`); None when it is still
    computing after the reads or unreachable. GitHub sends no event when a push clears a conflict, so a stored flag can
    outlive it."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    transport = connect(token, timeout, caller="pull_mergeable")
    for read in range(_MERGEABLE_READS):
        if read:
            time.sleep(_MERGEABLE_WAIT)
        try:
            answer = _MERGEABLE.get(get(transport, f"/repos/{repo}/pulls/{number}").get("mergeable"))
        except OSError:
            return None
        if answer:
            return answer
    return None


def connect(token: str | None, timeout: float = 30.0, caller: str = "other") -> Transport:
    """A transport to the GitHub API (`GITHUB_API_URL`, else api.github.com), signed in with `token` when there is one.
    Each call is logged under `caller`."""
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"} | (
        {"Authorization": f"Bearer {token}"} if token else {}
    )

    def send(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        request = urllib.request.Request(
            base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers
        )
        try:
            with _open(request, path, timeout, caller) as response:
                raw = response.read()
                decoded = json.loads(raw) if raw else {}
                if isinstance(decoded, list):  # a list endpoint's array comes back as `{"items": [...]}`
                    decoded = {"items": decoded}
                return response.status, decoded if isinstance(decoded, dict) else {}
        except urllib.error.HTTPError as exc:
            until = _reset_of(exc.headers, time.time()) if exc.code in (403, 429) else None
            if until is not None:
                raise RateLimited(exc.code, path, until) from exc
            return exc.code, {}
        except json.JSONDecodeError as exc:
            raise OSError(f"GitHub returned malformed JSON: {exc}") from exc

    return send


_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def connect_client(
    token: Callable[[], str | None],
    app_token: Callable[[], str] | None = None,
    timeout: float = 30.0,
    caller: str = "other",
) -> Client:
    """A conditional client to the GitHub API (`GITHUB_API_URL`, else api.github.com), signed in with the token `token`
    returns at each request, so a short-lived App token is read fresh. A path under `/app/` takes `app_token`'s App JWT
    instead, as GitHub accepts no other credential there. Each call is logged under `caller`."""
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    def send(method: str, path: str, etag: str | None) -> Reply:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if bearer := app_token() if app_token and path.startswith("/app/") else token():
            headers["Authorization"] = f"Bearer {bearer}"
        if etag:
            headers["If-None-Match"] = etag
        request = urllib.request.Request(base + path, method=method, headers=headers)
        try:
            with _open(request, path, timeout, caller) as response:
                raw = response.read()
                decoded = json.loads(raw) if raw else {}
                body = {"items": decoded} if isinstance(decoded, list) else decoded if isinstance(decoded, dict) else {}
                link = _NEXT.search(response.headers.get("Link", ""))
                following = link[1].removeprefix(base) if link else None
                return Reply(response.status, body, response.headers.get("ETag"), following)
        except urllib.error.HTTPError as exc:
            return Reply(exc.code, {}, etag if exc.code == 304 else None)
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
