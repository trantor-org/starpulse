"""The GitHub reads a head's rollup makes: its open pull requests, the base branch's required checks and what was posted."""

from __future__ import annotations

from typing import Any

from starpulse.github.adapters.outbound.rest import Transport, get
from starpulse.github.model.checks import required_of, results_of
from starpulse.github.ports.events import Head

__all__ = ["GitHubReader"]

#: GitHub's page size, and the most pages read of one list.
_PAGE = 100
_MAX_PAGES = 10


class GitHubReader:
    """Reads over `transport`, signed in with a token that can read rules, check runs, statuses and pull requests."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, _MAX_PAGES + 1):
            body = get(self._transport, f"{path}?per_page={_PAGE}&page={page}")
            got = body["items"] if key is None else body.get(key, [])
            items += got
            if len(got) < _PAGE:
                break
        return items

    def pulls(self, repository: str, sha: str) -> list[Head]:
        listed = self._pages(f"/repos/{repository}/commits/{sha}/pulls")
        return [
            Head(pull["number"], pull["base"]["ref"], bool(pull.get("draft")))
            for pull in listed
            if pull.get("state") == "open" and pull["head"]["sha"] == sha
        ]

    def required(self, repository: str, base: str) -> frozenset[str]:
        return required_of(self._pages(f"/repos/{repository}/rules/branches/{base}"))

    def results(self, repository: str, sha: str) -> dict[str, str]:
        runs = self._pages(f"/repos/{repository}/commits/{sha}/check-runs", "check_runs")
        statuses = self._pages(f"/repos/{repository}/commits/{sha}/status", "statuses")
        return results_of(runs, statuses)
