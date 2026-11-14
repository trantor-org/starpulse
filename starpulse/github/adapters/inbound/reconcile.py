"""The reconcile pass: recover the GitHub facts the inbox never received.

`reconcile` makes one pass, which the sweeper's `github` kind runs (`GithubKind`); there is no timer of its own. A pass
does two things, each alone so one failing does not stop the
other:

- It pages the App's deliveries back from a cursor and asks GitHub, once, to redeliver each GUID the inbox lacks.
- For each repository it pages the pull requests updated since a cursor and inserts a `source = 'reconcile'` row for each
  closed pull request and each finished check suite on its head, which the `events` consumer reads like a delivery.

Every list is read with its last ETag: a 304 spends no rate limit and changes nothing. The pull requests are walked
oldest first and their cursor is saved after each one a newer one follows, so a failed pass resumes after the last pull request it handled; a
cursor's ETag is saved only after everything its list covers was handled.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from starpulse.github.adapters.outbound.cursors import Cursor, SqlCursors
from starpulse.github.adapters.outbound.reconciled import Reconciled
from starpulse.github.adapters.outbound.rest import Client, GitHubError, Reply
from starpulse.github.model.github_config import GitHub
from starpulse.github.model.reconcile import LOOKBACK_S, SOURCE, epoch, pull_delivery, redeliveries, suite_delivery
from starpulse.github.ports.inbox import Inbox

__all__ = ["reconcile"]

logger = logging.getLogger(__name__)

_DELIVERIES = "/app/hook/deliveries?per_page=100"
_PULLS = "/repos/{}/pulls?state=all&sort=updated&direction=desc&per_page=100"
_ORG = "/orgs/{}/repos?per_page=100"


def _read(client: Client, path: str, etag: str | None = None) -> Reply:
    reply = client("GET", path, etag)
    if reply.status not in (200, 304):
        raise GitHubError(reply.status, path)
    return reply


def _newer(client: Client, path: str, cursor: Cursor | None, floor: float, stamp: str) -> tuple[Reply, list[dict[str, Any]]]:
    """The first page of a newest-first list, read conditionally on the cursor's ETag, and every item past `floor`."""
    first = _read(client, path, cursor.etag if cursor else None)
    found: list[dict[str, Any]] = []
    reply = first
    while reply.status == 200:
        page = reply.body.get("items", [])
        fresh = [item for item in page if epoch(item[stamp]) > floor]
        found += fresh
        if len(fresh) < len(page) or reply.next is None:
            break
        reply = _read(client, reply.next)
    return first, found


def _advance(cursors: SqlCursors, name: str, first: Reply, found: list[dict[str, Any]], stamp: str) -> None:
    if found:
        cursors.put(name, Cursor(max((item[stamp] for item in found), key=epoch), first.etag))


def _deliveries(client: Client, inbox: Inbox, cursors: SqlCursors, counted: Reconciled, now: float) -> None:
    cursor = cursors.get("deliveries")
    floor = epoch(cursor.value) if cursor else now - LOOKBACK_S
    first, attempts = _newer(client, _DELIVERIES, cursor, floor, "delivered_at")
    counted.looked()
    refused = 0
    for attempt in redeliveries(attempts, inbox.known({attempt["guid"] for attempt in attempts})):
        path = f"/app/hook/deliveries/{attempt}/attempts"
        answer = client("POST", path, None)
        if 200 <= answer.status < 300:
            counted.redelivered()
        else:
            refused += 1
            logger.warning("github reconcile: %s answered HTTP %s", path, answer.status)
    if not refused:
        _advance(cursors, "deliveries", first, attempts, "delivered_at")
    reached = cursors.get("deliveries")
    if reached:
        counted.lag("deliveries", now - epoch(reached.value))


def _pulls(client: Client, inbox: Inbox, cursors: SqlCursors, counted: Reconciled, repository: str, now: float) -> None:
    name = f"pull-rows:{repository}"
    cursor = cursors.get(name)
    floor = epoch(cursor.value) if cursor else now - LOOKBACK_S
    first, pulls = _newer(client, _PULLS.format(repository), cursor, floor, "updated_at")
    counted.looked()
    oldest = pulls[::-1]
    for pull, later in zip(oldest, [*oldest[1:], None]):
        head = (pull.get("head") or {}).get("sha", "")
        found = [(pull_delivery(repository, pull), "pull_request")]
        if head:
            suites = _read(client, f"/repos/{repository}/commits/{head}/check-suites").body.get("check_suites", [])
            found += [(suite_delivery(repository, pull["number"], head, suite), "check_suite") for suite in suites]
        for delivery, kind in found:
            if delivery is not None and inbox.save(delivery, SOURCE):
                counted.inserted(kind)
        if later and epoch(later["updated_at"]) > epoch(pull["updated_at"]):
            cursors.put(name, Cursor(pull["updated_at"], None))
    _advance(cursors, name, first, pulls, "updated_at")
    reached = cursors.get(name)
    if reached:
        counted.lag(name, now - epoch(reached.value))


def _repositories(client: Client, settings: GitHub) -> list[str]:
    """The listed repositories, and the organisation's unarchived ones when it is named."""
    names = list(settings.repositories)
    path: str | None = _ORG.format(settings.organisation) if settings.organisation else None
    while path:
        reply = _read(client, path)
        names += [repo["full_name"] for repo in reply.body.get("items", []) if not repo.get("archived")]
        path = reply.next
    return list(dict.fromkeys(names))


def reconcile(
    client: Client, inbox: Inbox, cursors: SqlCursors, settings: GitHub, counted: Reconciled, clock: Callable[[], float]
) -> None:
    """One pass over the App's deliveries and the pull requests of each repository `settings` accepts."""
    now = clock()
    try:
        _deliveries(client, inbox, cursors, counted, now)
    except Exception:
        logger.exception("github reconcile: deliveries")
    try:
        repositories = _repositories(client, settings)
    except Exception:
        logger.exception("github reconcile: repositories")
        return
    for repository in repositories:
        try:
            _pulls(client, inbox, cursors, counted, repository, now)
        except Exception:
            logger.exception("github reconcile: %s", repository)

