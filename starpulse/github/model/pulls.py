"""A pull request's address on github.com: the one place a pull request URL is read or written outside the REST client."""

import re
from typing import NamedTuple

__all__ = ["PullAt", "cited_pull", "pull_at", "pull_page", "pull_url"]

_URL = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?")
_CITED = re.compile(r"(?:https://github\.com/)?([^/\s#]+)/([^/\s#]+)(?:#|/pull/)(\d+)/?")


class PullAt(NamedTuple):
    owner: str
    name: str
    number: int

    @property
    def repo(self) -> str:
        return f"{self.owner}/{self.name}"


def pull_at(url: str) -> PullAt | None:
    """The pull request a github.com page URL names, None for any other text."""
    found = _URL.fullmatch(url)
    return PullAt(found[1], found[2], int(found[3])) if found else None


def cited_pull(text: str) -> PullAt | None:
    """The pull request `text` cites as `owner/name#N` or its page URL."""
    found = _CITED.fullmatch(text)
    return PullAt(found[1], found[2], int(found[3])) if found else None


def pull_page(repo: str, number: int | str) -> str:
    """The page path of a pull request without its scheme, the spelling a free-text line carries it in."""
    return f"github.com/{repo}/pull/{number}"


def pull_url(repo: str, number: int | str) -> str:
    """The page of the pull request `number` of `repo` (`owner/name`)."""
    return f"https://{pull_page(repo, number)}"
