"""The status checks a base branch's rulesets require, so a required check that never posted reads as missing.

The head's rollup marks a check required only once a run exists for it, so a required check that never posted is absent
from the rollup rather than shown. `SELECTION` reads the repository's rulesets in the same request as the pull request,
and `with_missing` lists each required context the rollup lacks as `missing`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

__all__ = ["SELECTION", "contexts", "with_missing"]

SELECTION = """
  defaultBranchRef { name }
  rulesets(first: 20) { nodes { target enforcement conditions { refName { include exclude } }
    rules(first: 20) { nodes { type parameters { ... on RequiredStatusChecksParameters { requiredStatusChecks { context } } } } }
  } }"""


def _ref_matches(ref: str, pattern: str) -> bool:
    """GitHub's ref-name glob: `*` and `?` stop at `/`, `**` crosses it, so `refs/heads/release/*` is not `release/a/b`."""
    glob = "".join(
        ".*" if part == "**" else "[^/]*" if part == "*" else "[^/]" if part == "?" else re.escape(part)
        for part in re.findall(r"\*\*|\*|\?|[^*?]+", pattern)
    )
    return re.fullmatch(glob, ref) is not None


def _applies(patterns: Iterable[str], base: str, default: str) -> bool:
    return any(
        pattern == "~ALL"
        or (pattern == "~DEFAULT_BRANCH" and base == default)
        or _ref_matches(f"refs/heads/{base}", pattern)
        for pattern in patterns
    )


def contexts(repository: dict[str, Any], base: str) -> list[str]:
    """The status-check contexts the active branch rulesets of `repository` (a GraphQL read with `SELECTION`) require of a pull request into `base`."""
    default = (repository.get("defaultBranchRef") or {}).get("name", "")
    found: list[str] = []
    for ruleset in ((repository.get("rulesets") or {}).get("nodes")) or []:
        refs = ((ruleset.get("conditions") or {}).get("refName")) or {}
        if (
            ruleset["target"] != "BRANCH"
            or ruleset["enforcement"] != "ACTIVE"
            or not _applies(refs.get("include", []), base, default)
            or _applies(refs.get("exclude", []), base, default)
        ):
            continue
        for rule in ruleset["rules"]["nodes"]:
            if rule["type"] == "REQUIRED_STATUS_CHECKS":
                found += [check["context"] for check in rule["parameters"]["requiredStatusChecks"]]
    return found


def with_missing(
    required: list[dict[str, str]], posted: Iterable[str | None], wanted: Iterable[str]
) -> list[dict[str, str]]:
    """`required` and a `missing` entry for each context in `wanted` that no check in `posted` carries the name of."""
    seen = set(posted)
    return required + [{"name": name, "result": "missing"} for name in dict.fromkeys(wanted) if name not in seen]
