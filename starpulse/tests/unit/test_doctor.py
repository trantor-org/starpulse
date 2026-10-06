"""`starpulse doctor`: each install check reports pass or fail, and any failure fails the run."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from starpulse import agent_cli as cli
from starpulse import doctor
from starpulse.adapter_kit import serve, task, url
from starpulse.board_feed import BoardFeed
from starpulse.config import Config, RunsInstance
from starpulse.tests.hosts import FakeHost
from starpulse.tests.machines import MACHINES

CHECKS = ["config", "server", "adapter:board", "adapter:nightly", "gh"]


def snapshot(**changes: Any) -> dict[str, Any]:
    """A snapshot of a server whose Board holds a task and whose `nightly` instance lists one workflow."""
    healthy = {
        "flows": [{"name": "board", "agents": [{"id": "PROJ-1"}]}],
        "dags": [{"name": "nightly/backup"}],
        "error": None,
    }
    return {**healthy, **changes}


CONFIG = Config(None, "ic", (RunsInstance("nightly", "dagu", "http://dagu:8080"),))


def check(report: dict[str, Any], name: str) -> dict[str, str]:
    return next(c for c in report["checks"] if c["check"] == name)


def test_every_check_passes_against_a_healthy_host_and_server() -> None:
    report = doctor.run_checks(snapshot(), CONFIG, FakeHost().probes(), "http://localhost:8766")

    assert report["ok"] is True
    assert [c["check"] for c in report["checks"]] == CHECKS
    assert all(c["status"] == "pass" and c["reason"] for c in report["checks"])


FAULTS: list[tuple[str, str, Callable[[], tuple[Any, ...]], str]] = [
    ("config", "starpulse.toml: bad key", lambda: (snapshot(), "starpulse.toml: bad key", FakeHost()), "bad key"),
    (
        "server",
        "down",
        lambda: ("cannot reach StarPulse at http://localhost:8766", CONFIG, FakeHost()),
        "cannot reach",
    ),
    (
        "adapter:board",
        "still reading",
        lambda: (snapshot(error="board: reading backlog"), CONFIG, FakeHost()),
        "reading",
    ),
    ("adapter:nightly", "silent", lambda: (snapshot(dags=[]), CONFIG, FakeHost()), "no workflows"),
    ("adapter:nightly", "erroring", lambda: (snapshot(dags=[], error="nightly: 503"), CONFIG, FakeHost()), "503"),
    ("gh", "missing", lambda: (snapshot(), CONFIG, FakeHost(installed=())), "not installed"),
    ("gh", "logged out", lambda: (snapshot(), CONFIG, FakeHost(gh_login=False)), "not logged in"),
]


@pytest.mark.parametrize(("name", "fault", "build", "reason"), FAULTS, ids=[f"{n}-{f}" for n, f, _, _ in FAULTS])
def test_a_failing_check_fails_the_run_and_says_why(
    name: str, fault: str, build: Callable[[], tuple[Any, ...]], reason: str
) -> None:
    snap, config, host = build()

    report = doctor.run_checks(snap, config, host.probes(), "http://localhost:8766")

    assert report["ok"] is False
    assert check(report, name)["status"] == "fail"
    assert reason in check(report, name)["reason"]


def test_the_doctor_verb_prints_the_checks_and_exits_1_when_one_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doctor, "LIVE", FakeHost(gh_login=False).probes())
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "Ready"))
    with serve(tmp_path, feed) as server:
        code = cli.main(["doctor", "--server", url(server, "")], {})

    document = json.loads(capsys.readouterr().out)
    assert code == 1
    assert document["ok"] is False
    assert [c["check"] for c in document["checks"] if c["status"] == "fail"] == ["gh"]


def test_the_doctor_verb_exits_0_when_every_check_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doctor, "LIVE", FakeHost().probes())
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "Ready"))
    with serve(tmp_path, feed) as server:
        code = cli.main(["doctor", "--server", url(server, "")], {})

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["ok"] is True
    assert all(c["status"] == "pass" for c in document["checks"])
