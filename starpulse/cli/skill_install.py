"""The skills the package bundles and the copying of them into a harness's skills directory.

Each skill is a directory under `starpulse/skills`. An install writes `MARKER` beside a copy, holding the digest of what
it wrote, so a later install can tell a copy the bundle has outgrown (`outdated`) from one someone edited (`modified`).

A skill names its coupled phase machine with a `machine:` key in its front matter; the machine file sits in the skill
directory, so the copy carries it and the plugin path finds it there too. An install refuses, before it writes
anything, a named machine that is missing or a machine with a State that declares no role.
"""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import yaml

SOURCE = Path(__file__).parents[1] / "skills"
#: Each harness's documented discovery path, relative to a project or the home directory.
HARNESS_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills"}
MARKER = ".starpulse-install.json"


def names(source: Path = SOURCE) -> list[str]:
    return sorted(path.name for path in source.iterdir() if (path / "SKILL.md").is_file())


def _front_matter(name: str, source: Path) -> dict:
    return yaml.safe_load((source / name / "SKILL.md").read_text().split("---")[1])


def description(name: str, source: Path = SOURCE) -> str:
    return _front_matter(name, source)["description"]


def machine_of(name: str, source: Path = SOURCE) -> str | None:
    """The machine file the skill names beside it, or `None` when it names none."""
    return _front_matter(name, source).get("machine")


class _EveryNameRegistered(dict):
    """Claims every guard and action name, so the check reads a machine's shape without the adapter's Python."""

    def __contains__(self, name: object) -> bool:
        return True

    def __getitem__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


def _check_machines(source: Path) -> None:
    """Refuse the bundle when a skill names a missing machine or a machine has a State that declares no role."""
    # imported here: a read verb loads this module and must not pull in the state machine library
    from starpulse.machine_engine.adapters.machine_loader import load_machine
    from starpulse.machine_engine.model.machine_definition import Registry, role_of

    for name in names(source):
        file = machine_of(name, source)
        if file is None:
            continue
        path = source / name / file
        if not path.is_file():
            raise ValueError(f"{name} names machine {file}, which is missing")
        registry = Registry(guards=_EveryNameRegistered(), actions=_EveryNameRegistered())
        compiled = load_machine(path, registry)
        for state in compiled.roles:
            if role_of(compiled, state) is None:
                raise ValueError(f"{path}: state {state} declares no role")


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

    Raises `ValueError`, writing nothing, when a skill's machine is missing or unsound, or when a copy was modified
    since install and `force` is false.
    """
    _check_machines(source)
    plan =[(h, n, status(root, h, n, source)) for h in harnesses for n in names(source)]
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
