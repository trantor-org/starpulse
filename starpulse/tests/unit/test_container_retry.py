"""A container start the suite retries leaves no container behind from the attempt that failed."""

from typing import Any

import pytest

from starpulse.tests import conftest

pytest.importorskip("testcontainers")


class TimesOutOnce:
    """A container whose first start times out after the daemon may already have created it."""

    starts = 0

    def with_name(self, name: str) -> TimesOutOnce:
        self.name = name
        return self

    def start(self) -> TimesOutOnce:
        TimesOutOnce.starts += 1
        if TimesOutOnce.starts == 1:
            raise TimeoutError("the daemon did not answer in time")
        return self


def test_a_retried_start_removes_the_container_the_failed_attempt_named(monkeypatch: pytest.MonkeyPatch) -> None:
    removed: list[str] = []
    monkeypatch.setattr(conftest, "_remove_container", removed.append)
    monkeypatch.setattr(conftest, "_ABANDONED", [])
    from testcontainers.core.config import testcontainers_config  # noqa: PLC0415

    monkeypatch.setattr(testcontainers_config, "ryuk_disabled", testcontainers_config.ryuk_disabled)
    attempts: list[Any] = []

    def make() -> TimesOutOnce:
        attempts.append(TimesOutOnce())
        return attempts[-1]

    started = conftest._retried(make)

    assert started is attempts[1]
    assert removed == [attempts[0].name]
    assert attempts[0].name != attempts[1].name
    assert conftest._ABANDONED == [attempts[0].name]
