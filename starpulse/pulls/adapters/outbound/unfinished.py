"""The work a task whose pull requests merged still has, answered from its record, the pull request store and the
parent's declared submodule paths, so a merge spawns no process."""

import configparser
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_SECTION = re.compile(r'submodule "(.+)"')


def submodule_paths(gitmodules: Path) -> list[tuple[str, str]]:
    """`(name, path)` for each submodule a `.gitmodules` file declares; a missing file declares none."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(gitmodules)
    return [
        (found[1], parser[section]["path"]) for section in parser.sections() if (found := _SECTION.fullmatch(section))
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
