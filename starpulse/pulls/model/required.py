"""The status checks a base branch's rulesets require, so a required check that never posted reads as missing.

The head's rollup marks a check required only once a run exists for it, so a required check that never posted is absent
from the rollup rather than shown. `SELECTION` reads the repository's rulesets in the same request as the pull request,
and `with_missing` lists each required context the rollup lacks as `missing`.
"""

import re
from collections.abc import Iterable
from typing import Any

__all__ = ["SELECTION", "contexts", "rollup_state", "with_missing"]

SELECTION = """
  defaultBranchRef { name }
  rulesets(first: 20) { nodes { target enforcement conditions { refName { include exclude } }
    rules(first: 20) { nodes { type parameters { ... on RequiredStatusChecksParameters { requiredStatusChecks { context } } } } }
  } }"""


_GLOB_TOKEN = re.compile(
    r"(?P<deep>(?<![^/])\*\*/)|(?P<star>\*+)|(?P<one>\?)"
    r"|(?P<set>\[(?:[!^]|[!^]?[^\]]+)\])|(?P<text>[^*?\[]+|\[)"
)
_GLOB_PARTS = {"deep": "(?:.*/)?", "star": "[^/]*", "one": "[^/]"}


def _glob_part(token: re.Match[str]) -> str:
    kind, text = token.lastgroup, token.group()
    if kind == "set":
        negated = text[1] in "!^"
        body = (text[2:-1] if negated else text[1:-1]).replace("\\", "\\\\")
        if not body:
            return "[^/]"
        return f"(?!/)[{'^' if negated else '\\' * body.startswith('^')}{body}]"
    return _GLOB_PARTS.get(kind or "") or re.escape(text)


def _ref_matches(ref: str, pattern: str) -> bool:
    """GitHub's ref-name glob (fnmatch): `*`, `?` and a terminal `**` stop at `/`, a `**/` component crosses it and may match no
    directory, `[0-9]` is a character set and an empty `[!]` any one character, so `refs/heads/release/*` is not
    `release/a/b` and `release/**/*` is `release/1`."""
    return re.fullmatch("".join(_glob_part(token) for token in _GLOB_TOKEN.finditer(pattern)), ref) is not None


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


def rollup_state(checks: Iterable[dict[str, str]]) -> str:
    """The rollup state `checks` make: `failing` when any failed, `passed` when all passed, else `pending`."""
    results = {check["result"] for check in checks}
    return "failing" if "failing" in results else "passed" if results <= {"pass"} else "pending"
