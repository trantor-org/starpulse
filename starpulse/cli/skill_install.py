"""The skills the package bundles and the copying of them into a harness's skills directory.

Each skill is a directory under `starpulse/skills`. An install writes `MARKER` beside a copy, holding the digest of what
it wrote, so a later install can tell a copy the bundle has outgrown (`outdated`) from one someone edited (`modified`).
"""

import hashlib
import json
import shutil
from pathlib import Path

import yaml

SOURCE = Path(__file__).parents[1] / "skills"
#: Each harness's documented discovery path, relative to a project or the home directory.
HARNESS_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills"}
MARKER = ".starpulse-install.json"


def names(source: Path = SOURCE) -> list[str]:
    return sorted(path.name for path in source.iterdir() if (path / "SKILL.md").is_file())


def description(name: str, source: Path = SOURCE) -> str:
    front_matter = (source / name / "SKILL.md").read_text().split("---")[1]
    return yaml.safe_load(front_matter)["description"]


def _digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != MARKER:
            digest.update(path.relative_to(directory).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def status(root: Path, harness: str, name: str, source: Path = SOURCE) -> str:
    """`absent`, `installed` (the bundle's version), `outdated` (untouched, the bundle moved on) or `modified`.

    A directory this installer did not write has no marker, so it counts as modified: nothing proves it unchanged.
    """
    copy = root / HARNESS_DIRS[harness] / name
    if not copy.is_dir():
        return "absent"
    try:
        written = json.loads((copy / MARKER).read_text())["sha256"]
    except OSError, ValueError, KeyError, TypeError:
        return "modified"
    if _digest(copy) != written:
        return "modified"
    return "installed" if written == _digest(source / name) else "outdated"


def install(root: Path, harnesses: list[str], force: bool, source: Path = SOURCE) -> list[dict[str, str]]:
    """Copy every bundled skill under `root` for each harness; returns what each copy was before.

    Raises `ValueError`, writing nothing, when a copy was modified since install and `force` is false.
    """
    plan = [(h, n, status(root, h, n, source)) for h in harnesses for n in names(source)]
    modified = [str(root / HARNESS_DIRS[h] / n) for h, n, was in plan if was == "modified"]
    if modified and not force:
        raise ValueError(f"modified since install: {', '.join(modified)}; rerun with --force to replace")
    done = []
    for harness, name, was in plan:
        copy = root / HARNESS_DIRS[harness] / name
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(source / name, copy)
        (copy / MARKER).write_text(json.dumps({"sha256": _digest(copy)}))
        done.append({"harness": harness, "skill": name, "path": str(copy), "was": was})
    return done
