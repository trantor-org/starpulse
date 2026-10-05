"""`starpulse doctor`: each check of the install reports pass or fail with a reason, and any failure fails the run."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from redis.exceptions import ResponseError

from starpulse import agent_cli as cli
from starpulse import doctor
from starpulse.board_feed import BoardFeed
from starpulse.config import Config, RunsInstance
from starpulse.tests.hosts import FakeHost, FakeRedis
from starpulse.tests.machines import MACHINES
from starpulse.tests.serving import serve, url
from starpulse.tests.tasks import task

HOME = {"REDIS_URL": "redis://127.0.0.1:6380"}
CHECKS = ["config", "redis", "server", "adapter:board", "adapter:nightly", "gh", "stream-lag"]


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
    report = doctor.run_checks(snapshot(), CONFIG, HOME, FakeHost().probes(), "http://localhost:8766")

    assert report["ok"] is True
    assert [c["check"] for c in report["checks"]] == CHECKS
    assert all(c["status"] == "pass" and c["reason"] for c in report["checks"])


FAULTS: list[tuple[str, str, Callable[[], tuple[Any, ...]], str]] = [
    ("config", "starpulse.toml: bad key", lambda: (snapshot(), "starpulse.toml: bad key", HOME, FakeHost()), "bad key"),
    ("redis", "refused", lambda: (snapshot(), CONFIG, HOME, FakeHost(fake_redis=FakeRedis(up=False))), "6380"),
    ("redis", "no runtime", lambda: (snapshot(), CONFIG, {}, FakeHost(installed=("gh",))), "REDIS_URL"),
    ("redis", "bad port", lambda: (snapshot(), CONFIG, {"REDIS_URL": "redis://h:abc"}, FakeHost()), "malformed"),
    ("redis", "not redis", lambda: (snapshot(), CONFIG, {"REDIS_URL": "http://h"}, FakeHost()), "malformed"),
    ("redis", "runtime down", lambda: (snapshot(), CONFIG, {}, FakeHost(runtime_up=False)), "Cannot connect"),
    (
        "server",
        "down",
        lambda: ("cannot reach StarPulse at http://localhost:8766", CONFIG, HOME, FakeHost()),
        "cannot reach",
    ),
    (
        "adapter:board",
        "still reading",
        lambda: (snapshot(error="board: reading backlog"), CONFIG, HOME, FakeHost()),
        "reading",
    ),
    ("adapter:nightly", "silent", lambda: (snapshot(dags=[]), CONFIG, HOME, FakeHost()), "no workflows"),
    ("adapter:nightly", "erroring", lambda: (snapshot(dags=[], error="nightly: 503"), CONFIG, HOME, FakeHost()), "503"),
    ("gh", "missing", lambda: (snapshot(), CONFIG, HOME, FakeHost(installed=("docker",))), "not installed"),
    ("gh", "logged out", lambda: (snapshot(), CONFIG, HOME, FakeHost(gh_login=False)), "not logged in"),
    (
        "stream-lag",
        "behind",
        lambda: (
            snapshot(),
            CONFIG,
            HOME,
            FakeHost(fake_redis=FakeRedis(groups={"machine:events": [{"name": "g", "lag": 5000, "pending": 0}]})),
        ),
        "machine:events",
    ),
    (
        "stream-lag",
        "unreadable",
        lambda: (
            snapshot(),
            CONFIG,
            HOME,
            FakeHost(fake_redis=FakeRedis(groups={"machine:events": ResponseError("WRONGTYPE not a stream")})),
        ),
        "WRONGTYPE",
    ),
    (
        "stream-lag",
        "unmeasurable",
        lambda: (
            snapshot(),
            CONFIG,
            HOME,
            FakeHost(fake_redis=FakeRedis(groups={"runs:events": [{"name": "g", "lag": None, "pending": 0}]})),
        ),
        "lag cannot be measured",
    ),
]


@pytest.mark.parametrize(("name", "fault", "build", "reason"), FAULTS, ids=[f"{n}-{f}" for n, f, _, _ in FAULTS])
def test_a_failing_check_fails_the_run_and_says_why(
    name: str, fault: str, build: Callable[[], tuple[Any, ...]], reason: str
) -> None:
    snap, config, environ, host = build()

    report = doctor.run_checks(snap, config, environ, host.probes(), "http://localhost:8766")

    assert report["ok"] is False
    assert check(report, name)["status"] == "fail"
    assert reason in check(report, name)["reason"]


def test_a_stopped_valkey_container_is_found_when_redis_url_is_unset() -> None:
    host = FakeHost(container_port="0.0.0.0:49153")

    report = doctor.run_checks(snapshot(), CONFIG, {}, host.probes(), "http://localhost:8766")

    assert [(e["redis_host"], e["redis_port"], e["redis_ssl"]) for e in host.dialed] == [("127.0.0.1", 49153, False)]
    assert check(report, "redis")["status"] == "pass"


def test_a_rediss_url_is_dialed_over_tls_as_its_user() -> None:
    host = FakeHost()

    doctor.run_checks(snapshot(), CONFIG, {"REDIS_URL": "rediss://worker:s3cret@cache:6390"}, host.probes(), "")

    assert host.dialed == [
        {
            "redis_host": "cache",
            "redis_port": 6390,
            "redis_username": "worker",
            "redis_password": "s3cret",
            "redis_ssl": True,
        }
    ]


def test_a_redis_older_than_7_reports_no_lag_and_is_judged_by_its_pending_entries() -> None:
    old = FakeRedis(groups={"machine:events": [{"name": "g", "pending": 3}]})

    report = doctor.run_checks(snapshot(), CONFIG, HOME, FakeHost(fake_redis=old).probes(), "")

    assert check(report, "stream-lag") == {
        "check": "stream-lag",
        "status": "pass",
        "reason": "1 consumer groups, the furthest 3 entries behind",
    }


def test_redis_unset_with_a_runtime_but_no_container_is_auto_startable() -> None:
    report = doctor.run_checks(snapshot(), CONFIG, {}, FakeHost().probes(), "http://localhost:8766")

    assert check(report, "redis")["status"] == "pass"
    assert "docker" in check(report, "redis")["reason"]
    assert check(report, "stream-lag")["status"] == "pass"


def test_the_doctor_verb_prints_the_checks_and_exits_1_when_one_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doctor, "LIVE", FakeHost(gh_login=False).probes())
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "Ready"))
    with serve(tmp_path, feed) as server:
        code = cli.main(["doctor", "--server", url(server, "")], HOME)

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
        code = cli.main(["doctor", "--server", url(server, "")], HOME)

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["ok"] is True
    assert all(c["status"] == "pass" for c in document["checks"])
