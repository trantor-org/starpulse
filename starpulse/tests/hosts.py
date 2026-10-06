"""A doubled host for `starpulse doctor`: which tools are installed and what `gh` answers."""

import subprocess
from collections.abc import Sequence
from starpulse import doctor


class FakeHost:
    """The machine `doctor` probes: which tools are installed and what `gh auth status` answers."""

    def __init__(
        self,
        *,
        installed: Sequence[str] = ("gh",),
        gh_login: bool = True,
    ) -> None:
        self.installed = installed
        self.gh_login = gh_login

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.installed else None

    def run(self, argv: Sequence[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["gh", "auth", "status"]:
            ok = self.gh_login
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "" if ok else "You are not logged in\n")
        raise AssertionError(f"unexpected command {argv}")

    def probes(self) -> doctor.Probes:
        return doctor.Probes(which=self.which, run=self.run)
