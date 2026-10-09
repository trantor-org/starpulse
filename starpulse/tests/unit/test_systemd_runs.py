"""The systemd adapter: allowlisted timers as one-step workflows, read from `systemctl show` on a fake `systemctl`."""

from __future__ import annotations

import re

import pytest

from starpulse._internal.adapters import BUILT_IN, module_name
from starpulse._internal.adapters.runs import systemd
from starpulse._internal.api.adapter_kit import RunsAdapterKit
from starpulse.contracts.adapters import TaskKeys

STARTED = "Thu 2026-10-08 20:00:01 UTC"
EXITED = "Thu 2026-10-08 20:00:09 UTC"


class FakeSystemctl:
    """A `systemctl` that answers `show <unit> -p <property>...` from the properties it holds per `(user, unit)`.

    A unit it does not hold answers as systemd does, `LoadState=not-found`; `down` makes every call fail.
    """

    def __init__(self, units: dict[tuple[bool, str], dict[str, str]], down: str | None = None) -> None:
        self.units = units
        self.down = down
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if self.down:
            raise OSError(self.down)
        user = args[0] == "--user"
        verb, unit, *flags = args[1:] if user else args
        assert verb == "show"
        held = self.units.get((user, unit), {"LoadState": "not-found"})
        wanted = [flags[i + 1] for i, flag in enumerate(flags) if flag == "-p"]
        return "".join(f"{name}={held.get(name, '')}\n" for name in wanted)


def timer(service: str) -> dict[str, str]:
    return {"LoadState": "loaded", "Unit": service}


def service(active: str = "inactive", result: str = "success", started: str = STARTED, exited: str = EXITED) -> dict:
    return {
        "LoadState": "loaded",
        "ActiveState": active,
        "Result": result,
        "ExecMainStartTimestamp": started,
        "ExecMainExitTimestamp": exited,
    }


class Sink:
    def __init__(self) -> None:
        self.dags: list[dict] | None = None
        self.error: str | None = None

    def set_dags(self, dags, error, pools=None, startable=None) -> None:
        self.dags, self.error = dags, error


def one(unit: dict) -> dict:
    """The only workflow of a fake host with one timer, `t.timer`, activating `t.service`."""
    fake = FakeSystemctl({(False, "t.timer"): timer("t.service"), (False, "t.service"): unit})
    (dag,) = systemd.listing(fake, "t")
    return dag


class TestSystemdAdapter(RunsAdapterKit):
    """The adapter is allowlisted units in, `Dag` records out; a timer has no task keys, so any scheme and branches do."""

    keys = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))
    branches = {"feature/PROJ-1": "PROJ-1", "main": None}

    def produce(self) -> list[dict]:
        fake = FakeSystemctl(
            {
                (False, "a.timer"): timer("a.service"),
                (False, "a.service"): service(),
                (True, "b.timer"): timer("b.service"),
                (True, "b.service"): service(active="activating", result="success", exited=""),
                (False, "c.timer"): timer("c.service"),
                (False, "c.service"): service(result="exit-code"),
                (False, "d.timer"): timer("d.service"),
                (False, "d.service"): service(started="", exited=""),
            }
        )
        return systemd.listing(fake, "a, user/b.timer, c, d")


def test_the_systemd_type_is_built_in() -> None:
    assert BUILT_IN["systemd"] == "starpulse._internal.adapters.runs.systemd"
    assert module_name("systemd") == "starpulse._internal.adapters.runs.systemd"


def test_a_timer_is_a_workflow_named_by_its_stem_with_one_step_for_its_service() -> None:
    dag = one(service())

    assert dag["name"] == "t"
    assert dag["steps"] == [
        {"name": "t.service", "depends": [], "status": "succeeded", "raw": "inactive/success", "kind": None}
    ]


@pytest.mark.parametrize(
    ("unit", "status", "raw"),
    [
        (service(active="activating", exited=""), "running", "activating/success"),
        (service(active="active", exited=""), "running", "active/success"),
        (service(active="reloading", exited=""), "running", "reloading/success"),
        (service(active="deactivating"), "running", "deactivating/success"),
        (service(), "succeeded", "inactive/success"),
        (service(active="failed", result="exit-code"), "failed", "failed/exit-code"),
        (service(result="timeout"), "failed", "inactive/timeout"),
        (service(started="", exited=""), "not_started", "inactive/success"),
    ],
)
def test_the_service_state_becomes_the_workflow_and_step_status(unit: dict, status: str, raw: str) -> None:
    dag = one(unit)

    assert (dag["status"], dag["raw"]) == (status, raw)
    assert (dag["steps"][0]["status"], dag["steps"][0]["raw"]) == (status, raw)


def test_start_and_finish_are_the_service_main_process_times_in_utc() -> None:
    dag = one(service())

    assert (dag["startedAt"], dag["finishedAt"], dag["runId"]) == (
        "2026-10-08T20:00:01Z",
        "2026-10-08T20:00:09Z",
        "2026-10-08T20:00:01Z",
    )


def test_a_running_service_has_no_finish_and_a_never_run_one_has_no_run() -> None:
    running = one(service(active="activating"))
    never = one(service(started="", exited=""))

    assert (running["startedAt"], running["finishedAt"]) == ("2026-10-08T20:00:01Z", "")
    assert (never["runId"], never["startedAt"], never["finishedAt"]) == ("", "", "")


def test_a_user_entry_reads_the_user_manager_and_a_bare_one_the_system_manager() -> None:
    fake = FakeSystemctl(
        {
            (True, "u.timer"): timer("u.service"),
            (True, "u.service"): service(),
            (False, "s.timer"): timer("s.service"),
            (False, "s.service"): service(),
        }
    )

    dags = systemd.listing(fake, "user/u, s.timer")

    assert [d["name"] for d in dags] == ["u", "s"]
    user_calls = [c for c in fake.calls if c[0] == "--user"]
    assert {c[2] for c in user_calls} == {"u.timer", "u.service"}
    assert {c[1] for c in fake.calls if c[0] != "--user"} == {"s.timer", "s.service"}


def test_the_allowlist_keeps_its_order_and_a_name_without_the_suffix_means_the_timer() -> None:
    names = [("a", "a.timer"), ("user/b.timer", "b.timer"), (" c ", "c.timer")]

    assert [systemd.entry(raw)[1] for raw, _ in names] == [unit for _, unit in names]
    assert systemd.entry("user/b")[0] is True


@pytest.mark.parametrize("url", ["", " , ", "a,a", "a,user/a.timer"])
def test_an_empty_allowlist_or_two_timers_of_one_stem_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="timer"):
        systemd.units(url)


def test_a_missing_allowlisted_timer_is_an_error_not_a_dropped_unit() -> None:
    fake = FakeSystemctl({(False, "t.timer"): timer("t.service"), (False, "t.service"): service()})

    with pytest.raises(OSError, match="nowhere.timer"):
        systemd.listing(fake, "t, nowhere")


def test_a_timer_whose_service_is_missing_is_an_error() -> None:
    fake = FakeSystemctl({(False, "t.timer"): timer("t.service")})

    with pytest.raises(OSError, match="t.service"):
        systemd.listing(fake, "t")


def test_reconcile_publishes_the_workflows_and_clears_the_error() -> None:
    sink = Sink()
    fake = FakeSystemctl({(False, "t.timer"): timer("t.service"), (False, "t.service"): service()})

    systemd.reconcile(sink, fake, "t")

    assert [d["name"] for d in sink.dags] == ["t"]
    assert sink.error is None


def test_a_failing_systemctl_sets_the_instance_error_and_publishes_no_workflows() -> None:
    sink = Sink()

    systemd.reconcile(sink, FakeSystemctl({}, down="Failed to connect to bus"), "t")

    assert sink.dags is None
    assert "Failed to connect to bus" in sink.error


def test_a_missing_unit_sets_the_instance_error() -> None:
    sink = Sink()

    systemd.reconcile(sink, FakeSystemctl({}), "nowhere")

    assert sink.dags is None
    assert "nowhere.timer" in sink.error


def test_a_timestamp_not_in_utc_sets_the_instance_error() -> None:
    sink = Sink()
    fake = FakeSystemctl(
        {
            (False, "t.timer"): timer("t.service"),
            (False, "t.service"): service(started="Thu 2026-10-08 13:00:01 MST"),
        }
    )

    systemd.reconcile(sink, fake, "t")

    assert sink.dags is None
    assert "unreadable response" in sink.error


def test_start_returns_none_because_a_timer_has_no_run_now() -> None:
    assert systemd.start("systemd-tmpfiles-clean, user/claude-sessions-snapshot") is None
