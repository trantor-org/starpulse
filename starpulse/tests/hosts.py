"""A doubled host for `starpulse doctor`: which tools are installed, what `gh` and a container runtime answer, a Redis."""

import subprocess
from collections.abc import Sequence
from typing import Any

import redis.exceptions

from starpulse import doctor
from starpulse.runtime import CONTAINER


class FakeRedis:
    """A Redis that answers `ping` and reports consumer groups per stream, or fails the way a down server does."""

    def __init__(self, *, up: bool = True, groups: dict[str, list[dict[str, Any]] | Exception] | None = None) -> None:
        self.up = up
        self.groups = groups if groups is not None else {}

    def ping(self) -> bool:
        if not self.up:
            raise redis.exceptions.ConnectionError("connection refused")
        return True

    def xinfo_groups(self, stream: str) -> list[dict[str, Any]]:
        if stream not in self.groups:
            raise redis.exceptions.ResponseError("no such key")
        if isinstance(found := self.groups[stream], Exception):
            raise found
        return found


class FakeHost:
    """The machine `doctor` probes: which tools are installed, what `gh auth status`, `<runtime> port` and
    `<runtime> info` answer."""

    def __init__(
        self,
        *,
        installed: Sequence[str] = ("gh", "docker"),
        gh_login: bool = True,
        container_port: str | None = None,
        runtime_up: bool = True,
        fake_redis: FakeRedis | None = None,
    ) -> None:
        self.installed = installed
        self.gh_login = gh_login
        self.container_port = container_port
        self.runtime_up = runtime_up
        self.redis = fake_redis or FakeRedis()
        self.dialed: list[dict[str, Any]] = []

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.installed else None

    def run(self, argv: Sequence[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["gh", "auth", "status"]:
            ok = self.gh_login
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "" if ok else "You are not logged in\n")
        if argv[1:3] == ["port", CONTAINER]:
            port = self.container_port
            return subprocess.CompletedProcess(argv, 0 if port else 1, f"{port}\n" if port else "", "")
        if argv[1:] == ["info"]:
            up = self.runtime_up
            return subprocess.CompletedProcess(argv, 0 if up else 1, "", "" if up else "Cannot connect to the daemon\n")
        raise AssertionError(f"unexpected command {argv}")

    def connect(self, endpoint: dict[str, Any]) -> FakeRedis:
        self.dialed.append(endpoint)
        return self.redis

    def probes(self) -> doctor.Probes:
        return doctor.Probes(which=self.which, run=self.run, redis=self.connect)
