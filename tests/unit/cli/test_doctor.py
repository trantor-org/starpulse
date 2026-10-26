"""`starpulse doctor`: each install check reports pass or fail, and any failure fails the run."""

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.cli import agent_cli as cli
from starpulse.cli import doctor
from starpulse.pulls.pins import Repo
from starpulse.runs.config import RunsInstance
from starpulse.runtime.adapter_kit import serve, task, url
from starpulse.runtime.config import Config

from tests.dagu_stub import dagu
from tests.hosts import FakeHost
from tests.machines import MACHINES, ROLES

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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "Ready"))
    with serve(tmp_path, feed) as server:
        code = cli.main(["doctor", "--server", url(server, "")], {})

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["ok"] is True
    assert all(c["status"] == "pass" for c in document["checks"])


CUE = {"event": "merged", "dag": "nightly/backup", "on": "merge", "resolves": "next", "state": "Done"}


def contract(commit: CommitKeys | None, repos: tuple[Repo, ...] = ()) -> Config:
    return Config(None, "ic", (RunsInstance("nightly", "dagu", "http://dagu:8080", commit=commit),), repos=repos)


def cued(*cues: dict[str, str]) -> dict[str, Any]:
    return snapshot(cues=list(cues))


def test_a_cued_dag_whose_commit_key_it_declares_passes() -> None:
    host = FakeHost(dags={"backup": ["AFTER", "BEFORE"]})

    report = doctor.run_checks(cued(CUE), contract(CommitKeys(after="AFTER", before="BEFORE")), host.probes(), "s")

    assert report["ok"] is True
    assert check(report, "cue:nightly/backup")["status"] == "pass"


def test_a_cue_naming_a_dag_the_instance_does_not_list_fails() -> None:
    report = doctor.run_checks(
        cued({**CUE, "dag": "nightly/gone"}), contract(CommitKeys(after="AFTER")), FakeHost().probes(), "s"
    )

    assert report["ok"] is False
    assert check(report, "cue:nightly/gone")["status"] == "fail"
    assert "no configured instance lists nightly/gone" in check(report, "cue:nightly/gone")["reason"]


def test_a_commit_key_the_dag_does_not_declare_fails_and_names_the_key() -> None:
    host = FakeHost(dags={"backup": ["BEFORE"]})

    report = doctor.run_checks(cued(CUE), contract(CommitKeys(after="AFTER", before="BEFORE")), host.probes(), "s")

    assert report["ok"] is False
    assert check(report, "cue:nightly/backup")["status"] == "fail"
    assert "after=AFTER" in check(report, "cue:nightly/backup")["reason"]
    assert "before=" not in check(report, "cue:nightly/backup")["reason"]


@pytest.mark.parametrize("commit", [None, CommitKeys(before="BEFORE")], ids=["no-table", "no-after-key"])
def test_a_cued_dag_with_no_commit_key_warns_time_inferred_without_failing(commit: CommitKeys | None) -> None:
    report = doctor.run_checks(cued(CUE), contract(commit), FakeHost().probes(), "s")

    assert report["ok"] is True
    assert check(report, "cue:nightly/backup")["status"] == "warn"
    assert "time-inferred" in check(report, "cue:nightly/backup")["reason"]


def test_two_cues_of_one_dag_are_one_check() -> None:
    report = doctor.run_checks(cued(CUE, {**CUE, "event": "reopened"}), contract(None), FakeHost().probes(), "s")

    assert [c["check"] for c in report["checks"]].count("cue:nightly/backup") == 1


def test_a_dagu_that_cannot_be_read_fails_the_cue_with_the_reason() -> None:
    host = FakeHost(dagu_down=True)

    report = doctor.run_checks(cued(CUE), contract(CommitKeys(after="AFTER")), host.probes(), "s")

    assert check(report, "cue:nightly/backup")["status"] == "fail"
    assert "Dagu unreachable" in check(report, "cue:nightly/backup")["reason"]


def test_a_repo_path_the_parent_holds_as_a_submodule_passes_and_any_other_fails() -> None:
    repos = (Repo("starpulse", "starpulse", "pin-bump"), Repo("docs", "docs", "pin-bump"))
    host = FakeHost(submodules=("starpulse",))

    report = doctor.run_checks(snapshot(), contract(None, repos), host.probes(), "s")

    assert check(report, "repo:starpulse")["status"] == "pass"
    assert check(report, "repo:docs")["status"] == "fail"
    assert "not a submodule" in check(report, "repo:docs")["reason"]
    assert report["ok"] is False


def test_an_unreadable_config_or_server_runs_no_contract_checks() -> None:
    down = doctor.run_checks("cannot reach", contract(CommitKeys(after="AFTER")), FakeHost().probes(), "s")
    bad = doctor.run_checks(cued(CUE), "starpulse.toml: bad key", FakeHost().probes(), "s")

    assert not [c for c in down["checks"] + bad["checks"] if c["check"].startswith(("cue:", "repo:"))]


def polled(problem: str | None, **host: Any) -> doctor.Probes:
    return dataclasses.replace(FakeHost(**host).probes(), poller=lambda: problem)


def test_a_poller_that_beats_passes_and_one_that_stopped_fails_the_run_with_why() -> None:
    up = doctor.contract(snapshot(), CONFIG, polled(None))
    down = doctor.contract(snapshot(), CONFIG, polled("the pull poller last reported 90s ago"))

    assert check(up, "poller:pulls")["status"] == "pass"
    assert up["ok"] is True
    assert check(down, "poller:pulls") == {
        "check": "poller:pulls",
        "status": "fail",
        "reason": "the pull poller last reported 90s ago",
    }
    assert down["ok"] is False


def test_no_poller_check_without_a_beat_to_read_or_a_poller_to_run() -> None:
    unread = doctor.contract(snapshot(), CONFIG, FakeHost().probes())
    off = doctor.contract(snapshot(), dataclasses.replace(CONFIG, pull_requests=False), polled("down"))
    no_gh = doctor.contract(snapshot(), CONFIG, polled("down", installed=()))

    assert not [c for report in (unread, off, no_gh) for c in report["checks"] if c["check"] == "poller:pulls"]


def test_the_servers_poller_check_joins_the_cli_report_and_its_other_checks_do_not() -> None:
    served = doctor.contract(snapshot(), CONFIG, polled("the pull poller has not reported"))
    served["checks"].append({"check": "repo:other", "status": "fail", "reason": "x"})

    report = doctor.run_checks(snapshot(), CONFIG, FakeHost().probes(), "s", served)

    assert [c["check"] for c in report["checks"]] == [*CHECKS, "poller:pulls"]
    assert report["ok"] is False


def test_the_default_read_goes_through_the_runs_adapter_to_a_real_dagu() -> None:
    with dagu({"backup": ["run"]}, params={"backup": ["AFTER=", "BEFORE="]}) as (base_url, _):
        instance = RunsInstance("nightly", "dagu", base_url)

        assert doctor.LIVE.dag_params(instance, "backup") == ["AFTER", "BEFORE"]

    with pytest.raises(OSError):
        doctor.LIVE.dag_params(RunsInstance("nightly", "dagu", "http://127.0.0.1:9"), "backup")
