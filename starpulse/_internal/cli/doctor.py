"""The checks behind `starpulse doctor`, each reported as pass, warn or fail with why.

The checks cover config loading, the server, each configured adapter, the GitHub CLI, and the contract between the
config and the machines' DAG cues: each cued DAG exists and takes the parameter its `[runs.commit]` key names, and each
`[[repos]]` path is a submodule. A warning (a cued DAG paired with its merge only by time) never fails the run. One
failure never stops the others, so a report names every fault at once.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starpulse._internal.config.config import Config, RunsInstance, runs_adapter

#: Seconds a `gh` command may take.
_COMMAND_TIMEOUT = 10


def _declared_params(instance: RunsInstance, workflow: str) -> list[str] | None:
    """The parameter names `workflow` declares, read through the instance's runs adapter; none when the adapter
    offers no `declared_params(url, workflow)`. Raises `OSError` when the scheduler cannot be read."""
    reader = getattr(runs_adapter(instance.type or ""), "declared_params", None)
    return reader(instance.url, workflow) if reader else None


@dataclass(frozen=True)
class Probes:
    """What the checks touch outside the process: installed tools and commands."""

    which: Callable[[str], str | None]
    run: Callable[..., subprocess.CompletedProcess[str]]
    dag_params: Callable[[RunsInstance, str], list[str] | None] = _declared_params
    """The parameter names a workflow of a runs instance declares, none when its adapter cannot say; raises `OSError`
    when the scheduler cannot be read."""


LIVE = Probes(
    which=shutil.which,
    run=subprocess.run,
)


def _result(check: str, ok: bool, reason: str) -> dict[str, str]:
    return {"check": check, "status": "pass" if ok else "fail", "reason": reason}


def _warn(check: str, reason: str) -> dict[str, str]:
    return {"check": check, "status": "warn", "reason": reason}


def _command(probes: Probes, *argv: str) -> tuple[int, str]:
    """The exit code and trimmed output of `argv`; a command that cannot finish is a failure with its reason."""
    try:
        done = probes.run(list(argv), capture_output=True, text=True, check=False, timeout=_COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout.strip() if done.returncode == 0 else done.stderr.strip())


def _adapters(snapshot: dict[str, Any] | str, config: Config | str) -> list[dict[str, str]]:
    """One result per producer: the Board, then each configured runs instance that pulls (a push-only one has no adapter)."""
    instances = [] if isinstance(config, str) else [i.name for i in config.runs if i.type]
    if isinstance(snapshot, str):
        return [_result(f"adapter:{name}", False, "the server is unreachable") for name in ["board", *instances]]
    errors = (snapshot["error"] or "").split("; ")
    board = next(flow for flow in snapshot["flows"] if flow["name"] == "board")
    found = [_board(board, errors)]
    for name in instances:
        error = next((e for e in errors if e.startswith(f"{name}: ")), None)
        listed = sum(dag["name"].startswith(f"{name}/") for dag in snapshot["dags"])
        if error:
            found.append(_result(f"adapter:{name}", False, error))
        elif not listed:
            found.append(_result(f"adapter:{name}", False, f"{name} lists no workflows"))
        else:
            found.append(_result(f"adapter:{name}", True, f"{name} lists {listed} workflows"))
    return found


def _board(board: dict[str, Any], errors: list[str]) -> dict[str, str]:
    if reading := next((e for e in errors if e.startswith("board: ")), None):
        return _result("adapter:board", False, reading)
    return _result("adapter:board", True, f"{len(board['agents'])} open tasks")


def _gh(probes: Probes) -> dict[str, str]:
    if not probes.which("gh"):
        return _result("gh", False, "gh is not installed, so a task's pull requests carry no state")
    code, text = _command(probes, "gh", "auth", "status")
    if code != 0:
        return _result("gh", False, f"gh auth status failed: {text}; run `gh auth login`")
    return _result("gh", True, "gh is logged in")


def _cue(cue: dict[str, Any], listed: set[str], instances: dict[str, RunsInstance], probes: Probes) -> dict[str, str]:
    """One cued DAG: it is listed, its instance's `[runs.commit]` keys are parameters it declares, and it has an `after` key."""
    dag = cue["dag"]
    name = f"cue:{dag}"
    if dag not in listed:
        return _result(name, False, f"no configured instance lists {dag}")
    instance = instances[dag.partition("/")[0]]
    keys = instance.commit
    if keys is None or keys.after is None:
        return _warn(name, f"{dag} has no [runs.commit] after key, so its runs are time-inferred against merges")
    named = {role: key for role in ("after", "before", "force", "task") if (key := getattr(keys, role))}
    try:
        read = probes.dag_params(instance, dag.partition("/")[2]) if instance.type and instance.url else None
    except (OSError, ValueError) as exc:
        return _result(name, False, f"cannot read the parameters of {dag}: {exc}")
    if read is None:
        return _result(name, True, f"{dag} is listed; its {instance.name} adapter does not report declared parameters")
    declared = set(read)
    if missing := [f"{role}={key}" for role, key in named.items() if key not in declared]:
        return _result(name, False, f"{dag} declares no parameter for [runs.commit] {', '.join(missing)}")
    return _result(name, True, f"{dag} declares {', '.join(sorted(named.values()))}")


def _repo(path: str, name: str, probes: Probes) -> dict[str, str]:
    """One `[[repos]]` entry: the parent repository (the working directory) holds `path` as a submodule (git mode 160000)."""
    code, text = _command(probes, "git", "ls-files", "--stage", "--", path)
    if code != 0:
        return _result(f"repo:{name}", False, f"git ls-files failed: {text}; run doctor from the parent repository")
    if not text.startswith("160000"):
        return _result(f"repo:{name}", False, f"{path} is not a submodule of this repository")
    return _result(f"repo:{name}", True, f"{path} is a submodule")


def _contract(snapshot: dict[str, Any] | str, config: Config | str, probes: Probes) -> list[dict[str, str]]:
    """The cue and repository checks; none while the snapshot or the config could not be read."""
    if isinstance(snapshot, str) or isinstance(config, str):
        return []
    listed = {dag["name"] for dag in snapshot["dags"]}
    instances = {i.name: i for i in config.runs}
    cues = {cue["dag"]: cue for cue in snapshot.get("cues", []) if "dag" in cue}
    return [
        *(_cue(cue, listed, instances, probes) for cue in cues.values()),
        *(_repo(repo.path, repo.name, probes) for repo in config.repos),
    ]


def _report(checks: list[dict[str, str]]) -> dict[str, Any]:
    return {"ok": all(c["status"] != "fail" for c in checks), "checks": checks}


def contract(snapshot: dict[str, Any], config: Config, probes: Probes) -> dict[str, Any]:
    """The cue and repository checks alone, as `run_checks` reports them: what the Ledger's banner reads."""
    return _report(_contract(snapshot, config, probes))


def run_checks(snapshot: dict[str, Any] | str, config: Config | str, probes: Probes, server: str) -> dict[str, Any]:
    """Every check as `{ok, checks: [{check, status, reason}]}`.

    `snapshot` is the server's snapshot, or the reason it could not be read; `config` is the loaded config, or the
    reason it could not be loaded; `server` is the address the snapshot was read from."""
    checks = [
        _result(
            "config", *((False, config) if isinstance(config, str) else (True, f"{len(config.runs)} runs instances"))
        ),
        _result("server", *((False, snapshot) if isinstance(snapshot, str) else (True, f"{server} answers"))),
        *_adapters(snapshot, config),
        _gh(probes),
        *_contract(snapshot, config, probes),
    ]
    return _report(checks)

