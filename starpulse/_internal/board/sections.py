"""Reading a task body's `## <heading>` sections and the fenced YAML they hold."""

from __future__ import annotations

import re

import yaml

__all__ = ["fenced_list", "under"]

#: The `## <heading>` lines that bound a body's sections.
_HEADING = re.compile(r"^##[ \t]+(.*?)[ \t]*$", re.M)
#: The first fenced YAML block of a section.
_FENCE = re.compile(r"```ya?ml\n(.*?)\n```", re.S)


def under(body: str, heading: str) -> str | None:
    """The text under the body's `## <heading>` up to the next `##` heading, or None when it has no such section."""
    heads = list(_HEADING.finditer(body))
    for number, head in enumerate(heads):
        if head[1].casefold() == heading.casefold():
            end = heads[number + 1].start() if number + 1 < len(heads) else len(body)
            return body[head.end() : end].strip()
    return None


def fenced_list(body: str, heading: str, key: str) -> list | None:
    """The list under `key` in the first fenced YAML of `## <heading>`, or None when the section, the block or the key is missing.

    Raises `ValueError` when the block is not YAML, or holds `key` as something other than a list.
    """
    text = under(body, heading)
    fenced = _FENCE.search(text) if text else None
    if not fenced:
        return None
    try:
        parsed = yaml.safe_load(fenced.group(1))
    except yaml.YAMLError as error:
        raise ValueError(f"{heading} block is not YAML: {error}") from error
    if not isinstance(parsed, dict) or key not in parsed:
        return None
    if not isinstance(parsed[key], list):
        raise ValueError(f"{heading} `{key}` is not a list")
    return parsed[key]
