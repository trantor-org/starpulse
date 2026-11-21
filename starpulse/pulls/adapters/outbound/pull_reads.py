"""The three PR store fields no delivery carries, read by the App-signed REST client with `If-None-Match`.

`refresh` reads only what a delivery names (the spec's Field Sources table): a pull request's changed files on `opened`
and `synchronize`, the commits behind its base on `synchronize` and on a `push` to the base, a base's required contexts
on its first pull request and on each `repository_ruleset`. Each read sends the stored ETag, so a 304 spends no rate
limit and leaves the record as it was; there is no timer. A read GitHub refuses raises `GitHubError`, which fails the
delivery on the queue's bounded backoff.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from starpulse.github.adapters.outbound.cursors import Cursor, SqlCursors
from starpulse.github.adapters.outbound.rest import Client, GitHubError, Reply
from starpulse.github.model.checks import required_of
from starpulse.github.model.delivery import Delivery
from starpulse.pulls.adapters.outbound.pull_events import bare_detail
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.pulls.model.required import with_missing

__all__ = ["READ_EVENTS", "PullReads", "refresh"]

#: The deliveries besides `pull_request` that name a read.
READ_EVENTS = frozenset({"push", "repository_ruleset"})

#: GitHub's page size, and the pages of a pull request's files: its listing stops at 3000.
_PAGE = 100
_FILES_PAGES = 30
_RULE_PAGES = 5
_HEADS = "refs/heads/"


class PullReads:
    """Reads over `client`, keeping each read's ETag (and a base's required contexts) in `etags`."""

    def __init__(self, client: Client, etags: SqlCursors) -> None:
        self._client, self._etags = client, etags

    def _read(self, path: str, etag: str | None, pages: int = 1) -> tuple[Reply, list[dict[str, Any]]] | None:
        """Every page of `path`, the first sent with `etag`; None when GitHub answers 304."""
        first = reply = self._client("GET", path, etag)
        if first.status == 304:
            return None
        items: list[dict[str, Any]] = []
        for _ in range(pages):
            if reply.status != 200:
                raise GitHubError(reply.status, path)
            items += reply.body.get("items", [])
            if reply.next is None:
                break
            reply = self._client("GET", reply.next, None)
        return first, items

    def files(
        self, repository: str, number: int, held: list[str] | None, save: Callable[[list[str] | None], bool]
    ) -> None:
        """Pass `save` the paths pull request `number` changes (None when the listing is cut at its cap), and keep the
        ETag only once it says it saved them: a failed or skipped save leaves the prior ETag, so the read repeats.
        Nothing is saved when GitHub answers 304."""
        name = f"files:{repository}#{number}"
        path = f"/repos/{repository}/pulls/{number}/files?per_page={_PAGE}"
        stored = self._etags.get(name)
        got = self._read(path, stored.etag if stored and held is not None else None, _FILES_PAGES)
        if got is None:
            return
        first, items = got
        if save(None if len(items) >= _PAGE * _FILES_PAGES else [item["filename"] for item in items]):
            self._etags.put(name, Cursor("", first.etag))

    def behind(
        self, repository: str, number: int, head: str, base: str, held: int | None, save: Callable[[int], bool]
    ) -> None:
        """Pass `save` the commits `base` has that `head` lacks, keeping the ETag only once it says it saved them;
        nothing is saved when GitHub answers 304."""
        name = f"behind:{repository}#{number}"
        path = f"/repos/{repository}/compare/{head}...{base}?per_page=1"
        stored = self._etags.get(name)
        got = self._read(path, stored.etag if stored and held is not None else None)
        if got is None:
            return
        first, _ = got
        if save(first.body["ahead_by"]):
            self._etags.put(name, Cursor("", first.etag))

    def required(self, repository: str, base: str, force: bool) -> frozenset[str]:
        """The contexts the rules of `base` require; without `force` a base read before makes no request."""
        name = f"required:{repository}:{base}"
        stored = self._etags.get(name)
        if stored and not force:
            return frozenset(json.loads(stored.value))
        path = f"/repos/{repository}/rules/branches/{base}?per_page={_PAGE}"
        got = self._read(path, stored.etag if stored else None, _RULE_PAGES)
        if got is None:
            return frozenset(json.loads(stored.value)) if stored else frozenset()
        first, items = got
        contexts = required_of(items)
        self._etags.put(name, Cursor(json.dumps(sorted(contexts)), first.etag))
        return contexts


def _detailed(store: PullStore, repository: str, number: int, now: float) -> dict[str, Any]:
    (record,) = store.find(repository, number, detailed=True)
    return record | {"detail": record["detail"] or bare_detail(now)}


def _amend(store: PullStore, record: dict[str, Any], change: Callable[[dict[str, Any]], dict[str, Any]]) -> bool:
    """Apply `change`'s fields to the record held now, unless its head or base is no longer `record`'s, which a read
    made for the old one must not write; True when it saved."""

    def apply(current: dict[str, Any] | None) -> dict[str, Any] | None:
        if current is None or any(current[name] != record[name] for name in ("headRefOid", "baseRefName")):
            return None
        return current | change(current)

    return store.amend(record["repo"], record["number"], apply)


def _put(store: PullStore, record: dict[str, Any], **fields: Any) -> bool:
    return _amend(store, record, lambda current: {"detail": (current["detail"] or record["detail"]) | fields})


def _behind(store: PullStore, reads: PullReads, record: dict[str, Any], head: str, base: str) -> None:
    held = record["detail"].get("behindMain")
    reads.behind(
        record["repo"], record["number"], head, base, held, lambda behind: _put(store, record, behindMain=behind)
    )


def _requiring(store: PullStore, record: dict[str, Any], contexts: frozenset[str], now: float) -> None:
    def change(current: dict[str, Any]) -> dict[str, Any]:
        kept = [check for check in current["requiredChecks"] if check["name"] in contexts]
        added = with_missing(kept, (check["name"] for check in kept), sorted(contexts))
        checks = sorted(added, key=lambda check: check["name"])
        if {check["name"] for check in checks} == {check["name"] for check in current["requiredChecks"]}:
            return {"requiredChecks": checks}
        # the rollup counted the old contexts: a newer one of the new set outvotes it in `PullStore._guarded`
        results = {check["result"] for check in checks}
        state = "failing" if "failing" in results else "passed" if results == {"pass"} else "pending"
        return {"requiredChecks": checks, "rollup": {"sha": current["headRefOid"], "state": state, "at": now}}

    _amend(store, record, change)


def refresh(store: PullStore, reads: PullReads, delivery: Delivery, now: float) -> None:
    """Make the reads `delivery` names and save what they returned in the pull requests' records."""
    body = json.loads(delivery.body)
    repository = delivery.repository
    if delivery.event == "pull_request":
        pull: Mapping[str, Any] = body["pull_request"]
        record = _detailed(store, repository, pull["number"], now)
        if delivery.action in ("opened", "synchronize"):
            held = record["detail"].get("files")
            reads.files(repository, pull["number"], held, lambda files: _put(store, record, files=files))
            reads.required(repository, record["baseRefName"], force=False)
        if delivery.action == "synchronize":
            _behind(store, reads, record, record["headRefOid"], record["baseRefName"])
    elif delivery.event == "push":
        base = str(body.get("ref", "")).removeprefix(_HEADS)
        for open_pull in store.find(repository, state="OPEN"):
            if open_pull["baseRefName"] == base and open_pull["headRefOid"]:
                record = _detailed(store, repository, open_pull["number"], now)
                _behind(store, reads, record, record["headRefOid"], base)
    elif delivery.event == "repository_ruleset":
        opened = store.find(repository, state="OPEN")
        for base in sorted({pull["baseRefName"] for pull in opened}):
            contexts = reads.required(repository, base, force=True)
            for open_pull in opened:
                if open_pull["baseRefName"] == base:
                    _requiring(store, open_pull, contexts, now)
