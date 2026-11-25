"""The work a task whose pull requests merged still has, answered from its record, the pull request store and the
parent's declared submodule paths, so a merge spawns no process."""

import configparser
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_SECTION = re.compile(r'submodule "(.+)"')
_ESCAPES = {"n": "\n", "t": "\t", "b": "\b"}


def _git_value(raw: str) -> str:
    out: list[tuple[str, bool]] = []  # each character with whether quotes or an escape keep it through the trim
    quoted, escaped = False, False
    for char in raw:
        if escaped:
            out.append((_ESCAPES.get(char, char), True))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char in "#;" and not quoted:
            break
        else:
            out.append((char, quoted))
    start, end = 0, len(out)
    while start < end and out[start][0].isspace() and not out[start][1]:
        start += 1
    while end > start and out[end - 1][0].isspace() and not out[end - 1][1]:
        end -= 1
    return "".join(char for char, _ in out[start:end])


def submodule_paths(gitmodules: Path) -> list[tuple[str, str]]:
    """`(repository, path)` for each submodule a `.gitmodules` file declares, read as Git reads a value (quotes,
    escapes, comments): the repository is the url's last segment, the section's name when it has no url. A missing file
    declares none."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(gitmodules)
    return [
        (
            _git_value(section_url).rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") if (section_url := parser[section].get("url")) else found[1],
            _git_value(parser[section]["path"]),
        )
        for section in parser.sections()
        if (found := _SECTION.fullmatch(section))
    ]


def work_left(
    modified: Sequence[str],
    records: Sequence[Mapping[str, Any] | None],
    submodules: Sequence[tuple[str, str]],
    parent: str,
) -> list[str]:
    """Each repository in `modified` with no merged pull request among `records`: a file under a submodule's path
    belongs to that submodule, any other to the `parent`. A record the store does not hold covers nothing, and an
    unchecked Acceptance Criterion is no work left."""
    covered = {record["repo"].rsplit("/", 1)[-1] for record in records if record and record["state"] == "MERGED"}
    repos = dict.fromkeys(
        next((name for name, root in submodules if path == root or path.startswith(f"{root}/")), parent)
        for path in modified
    )
    return [f"{repo} has no merged pull request" for repo in repos if repo not in covered]
