"""A doubled host for `starpulse doctor`: which tools are installed, what `gh` answers, which paths are submodules and
which parameters Dagu says each DAG declares."""

import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from starpulse import doctor
from starpulse.config import RunsInstance


class FakeHost:
    """The machine `doctor` probes: which tools are installed and what `gh auth status` answers."""

    def __init__(
        self,
        *,
        installed: Sequence[str] = ("gh",),
        gh_login: bool = True,
        submodules: Sequence[str] = (),
        dags: Mapping[str, Sequence[str]] | None = None,
        dagu_down: bool = False,
    ) -> None:
        self.installed = installed
        self.gh_login = gh_login
        self.submodules = submodules
        self.dags = {} if dags is None else dags
        self.dagu_down = dagu_down

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.installed else None

    def run(self, argv: Sequence[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["gh", "auth", "status"]:
            ok = self.gh_login
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "" if ok else "You are not logged in\n")
        if argv[:3] == ["git", "ls-files", "--stage"]:
            path = argv[-1]
            return subprocess.CompletedProcess(
                argv, 0, f"160000 abc123 0\t{path}\n" if path in self.submodules else "", ""
            )
        raise AssertionError(f"unexpected command {argv}")

    def dag_params(self, instance: RunsInstance, name: str) -> list[str] | None:
        if self.dagu_down:
            raise OSError(f"Dagu unreachable at {instance.url}")
        return list(self.dags[name]) if name in self.dags else None

    def probes(self) -> doctor.Probes:
        return doctor.Probes(which=self.which, run=self.run, dag_params=self.dag_params)
