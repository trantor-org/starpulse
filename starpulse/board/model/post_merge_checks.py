"""A task's `## Post-merge Checks`: the block a client declares, the verdict comment that closes a check.

The block is a fenced YAML list under `post_merge_checks:`. A check is `{id, text, within, pass}` and optionally `when`
and `fail`: `text` says the claim, `within` the deadline after the merge (`90m`, `12h` or `1d`), and `when`, `fail` and
`pass` are criteria. A criterion is a table with a `kind` the client names and the keys that kind reads, and an
optional `id`; StarPulse evaluates none, so any kind is accepted. A check's verdict is a comment that opens
`[post-merge-check] <id> PASS` or `... MISS`, the one line a client that reads comments can match.
"""

from __future__ import annotations

import re
from typing import Any

from starpulse.board.model.sections import fenced_list

__all__ = ["HEADING", "KEY", "MARKER", "parse", "verdict_comment", "verdict_of"]

HEADING = "Post-merge Checks"
KEY = "post_merge_checks"
MARKER = "[post-merge-check]"
_ROLES = ("when", "fail", "pass")
_KEYS = {"id", "text", "within", *_ROLES}
_WITHIN = re.compile(r"\A([1-9]\d*)[mhd]\Z")


def parse(body: str) -> list[dict[str, Any]] | None:
    """The checks a body declares, None when it has no block; raises `ValueError` naming what is malformed."""
    checks = fenced_list(body, HEADING, KEY)
    seen: set[str] = set()
    for check in checks or []:
        label = check.get("id", "?") if isinstance(check, dict) else "?"
        if reason := _check_error(check):
            raise ValueError(f"post-merge check {label}: {reason}")
        if check["id"] in seen:
            raise ValueError(f"post-merge checks share duplicate id {check['id']!r}")
        seen.add(check["id"])
    return checks


def _check_error(check: Any) -> str | None:
    if not isinstance(check, dict):
        return "check is not a mapping"
    if not isinstance(check.get("id"), str) or not check["id"]:
        return "missing 'id'"
    if unknown := sorted(set(check) - _KEYS):
        return f"unknown key {unknown[0]!r}"
    for required in ("text", "pass", "within"):
        if not check.get(required):
            return f"missing {required!r}"
    if not _WITHIN.match(str(check["within"]).strip()):
        return f"within {check['within']!r} is not a positive duration such as 90m, 12h or 1d"
    for role in _ROLES:
        if role in check and (reason := _criterion_error(check[role])):
            return f"{role}: {reason}"
    return None


def _criterion_error(criterion: Any) -> str | None:
    if not isinstance(criterion, dict):
        return "criterion is not a mapping"
    if not isinstance(criterion.get("kind"), str) or not criterion["kind"]:
        return "criterion needs a `kind` naming what it tests"
    if "id" in criterion and not isinstance(criterion["id"], str):
        return "criterion `id` is not a string"
    return None


def verdict_comment(check: str, verdict: str, evidence: str = "", fix: str | None = None) -> str:
    """The comment that records `verdict` (`pass` or `miss`) on `check`: the marker line, the fix's id on a miss, then the evidence."""
    lines = [f"{MARKER} {check} {verdict.upper()}", f"Fix: {fix}" if fix else "", evidence]
    return "\n".join(line for line in lines if line)


def verdict_of(comments: list[str], check: str) -> str | None:
    """`PASS` or `MISS` when a comment opens with `check`'s verdict line, else None."""
    pattern = re.compile(rf"\A{re.escape(MARKER)} {re.escape(check)} (PASS|MISS)$", re.M)
    return next((found[1] for comment in comments if (found := pattern.match(comment))), None)
