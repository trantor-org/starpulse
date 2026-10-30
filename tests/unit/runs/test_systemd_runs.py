"""The systemd adapter: allowlisted timers as one-step workflows, read from `systemctl show` on a fake `systemctl`."""

from __future__ import annotations

import os
import queue
import re
import threading
import time

import pytest
from starpulse.board.model.adapter_types import BUILT_IN, module_name
from starpulse.contracts.adapters import TaskKeys
from starpulse.runs.adapters.outbound import systemd
from starpulse.runtime.adapter_kit import RunsAdapterKit

STARTED = "Thu 2026-10-08 20:00:01 UTC"
EXITED = "Thu 2026-10-08 20:00:09 UTC"
STARTED_ISO = "2026-10-08T20:00:01Z"
FIRED_ISO = "2026-10-08T20:05:00Z"


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

    def set_dags(self, dags, error, pools=None, startable=None, cpu=None) -> None:
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
    assert BUILT_IN["systemd"] == "starpulse.runs.adapters.outbound.systemd"
    assert module_name("systemd") == "starpulse.runs.adapters.outbound.systemd"


def test_a_timer_is_a_workflow_named_by_its_stem_with_one_step_for_its_service() -> None:
    dag = one(service())

    assert dag["name"] == "t"
    assert dag["steps"] == [
        {
            "name": "t.service",
            "depends": [],
            "status": "succeeded",
            "raw": "inactive/success",
            "kind": None,
            "precondition": None,
            "lock": None,
            "last": [],
        }
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


def test_read_publishes_the_workflows_and_clears_the_error() -> None:
    sink = Sink()
    fake = FakeSystemctl({(False, "t.timer"): timer("t.service"), (False, "t.service"): service()})

    systemd.Timers(sink, fake, "t").read()

    assert [d["name"] for d in sink.dags] == ["t"]
    assert sink.error is None


def test_a_failing_systemctl_sets_the_instance_error_and_publishes_no_workflows() -> None:
    sink = Sink()

    systemd.Timers(sink, FakeSystemctl({}, down="Failed to connect to bus"), "t").read()

    assert sink.dags is None
    assert "Failed to connect to bus" in sink.error


def test_a_missing_unit_sets_the_instance_error() -> None:
    sink = Sink()

    systemd.Timers(sink, FakeSystemctl({}), "nowhere").read()

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

    systemd.Timers(sink, fake, "t").read()

    assert sink.dags is None
    assert "unreadable response" in sink.error


def test_start_returns_none_because_a_timer_has_no_run_now() -> None:
    assert systemd.start("systemd-tmpfiles-clean, user/claude-sessions-snapshot") is None


FIRED = "Thu 2026-10-08 20:05:00 UTC"
FIRED_DONE = "Thu 2026-10-08 20:05:03 UTC"


def host() -> FakeSystemctl:
    """A host with timers `a` and `b`, each last run at `STARTED`."""
    return FakeSystemctl(
        {
            (False, "a.timer"): timer("a.service"),
            (False, "a.service"): service(),
            (False, "b.timer"): timer("b.service"),
            (False, "b.service"): service(),
        }
    )


def fire(fake: FakeSystemctl, unit: str) -> None:
    """`unit` runs again at `FIRED`, as systemd records it before it signals the change."""
    fake.units[(False, unit)] = service(started=FIRED, exited=FIRED_DONE)


def started(sink: Sink) -> dict[str, str]:
    return {d["name"]: d["startedAt"] for d in sink.dags}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "/org/freedesktop/systemd1/unit/proxmox_2dfan_2dmetrics_2eservice: "
            "org.freedesktop.DBus.Properties.PropertiesChanged ('org.freedesktop.systemd1.Unit', {}, [])",
            "proxmox-fan-metrics.service",
        ),
        ("/org/freedesktop/systemd1/unit/a_2etimer: org.freedesktop.DBus.Properties.PropertiesChanged ()", "a.timer"),
        (
            "/org/freedesktop/systemd1: org.freedesktop.systemd1.Manager.JobNew (uint32 1, objectpath '/x', 'a.service')",
            None,
        ),
        ("/org/freedesktop/systemd1/unit/a_2eservice: org.freedesktop.systemd1.Unit.Other ()", None),
        ("Monitoring signals on object /org/freedesktop/systemd1 owned by org.freedesktop.systemd1", None),
    ],
)
def test_a_property_change_signal_names_the_unit_it_is_about(line: str, expected: str | None) -> None:
    assert systemd.changed_unit(line) == expected


def test_a_change_to_one_service_reads_only_that_timer_and_keeps_the_rest() -> None:
    sink, fake = Sink(), host()
    timers = systemd.Timers(sink, fake, "a, b")
    timers.read()
    fire(fake, "b.service")
    fake.calls.clear()

    timers.read({timers.owner(False, "b.service")})

    assert started(sink) == {"a": STARTED_ISO, "b": FIRED_ISO}
    assert [d["name"] for d in sink.dags] == ["a", "b"]
    assert {c[1] for c in fake.calls} == {"b.timer", "b.service"}


def test_a_timer_and_its_service_belong_to_one_timer_and_other_units_to_none() -> None:
    timers = systemd.Timers(Sink(), host(), "a, b")
    timers.read()

    assert timers.owner(False, "a.timer") == timers.owner(False, "a.service") == (False, "a.timer")
    assert timers.owner(True, "a.service") is None
    assert timers.owner(False, "other.service") is None


def test_a_failing_read_after_a_change_keeps_the_last_reading_and_shows_the_error() -> None:
    sink, fake = Sink(), host()
    timers = systemd.Timers(sink, fake, "a")
    timers.read()
    fake.down = "Failed to connect to bus"

    timers.read({(False, "a.timer")})

    assert sink.dags is None
    assert "Failed to connect to bus" in sink.error


def test_feed_queues_the_changes_of_watched_units_only() -> None:
    events: queue.Queue = queue.Queue()
    lines = [
        "/org/freedesktop/systemd1/unit/a_2eservice: org.freedesktop.DBus.Properties.PropertiesChanged ()",
        "/org/freedesktop/systemd1/unit/zzz_2eservice: org.freedesktop.DBus.Properties.PropertiesChanged ()",
        "/org/freedesktop/systemd1: org.freedesktop.systemd1.Manager.UnitNew ('a.service')",
    ]

    systemd.feed(True, lines, events, lambda user, unit: unit == "a.service")

    assert events.get_nowait() == (True, "a.service")
    assert events.empty()


def run_serve(timers: systemd.Timers, events: queue.Queue, **intervals: float) -> threading.Thread:
    stop = threading.Event()
    thread = threading.Thread(
        target=systemd.serve, args=(timers, events, stop), kwargs={"healthy": lambda: True, **intervals}, daemon=True
    )
    thread.stop = stop  # type: ignore[attr-defined]
    thread.start()
    return thread


def finish(thread: threading.Thread) -> None:
    thread.stop.set()  # type: ignore[attr-defined]
    thread.join(timeout=2)


def wait_for(condition, seconds: float = 2.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_signal_updates_the_dag_record_without_a_periodic_listing() -> None:
    sink, fake, events = Sink(), host(), queue.Queue()
    timers = systemd.Timers(sink, fake, "a, b")
    timers.read()
    thread = run_serve(timers, events, backstop=60.0, fallback=60.0, debounce=0.01)

    fire(fake, "a.service")
    events.put((False, "a.service"))

    assert wait_for(lambda: started(sink)["a"] == FIRED_ISO)
    finish(thread)
    assert started(sink)["b"] == STARTED_ISO


def test_idle_the_adapter_starts_no_systemctl_between_backstop_listings() -> None:
    sink, fake = Sink(), host()
    timers = systemd.Timers(sink, fake, "a, b")
    timers.read()
    fake.calls.clear()
    thread = run_serve(timers, queue.Queue(), backstop=60.0, fallback=0.01, debounce=0.01)

    time.sleep(0.3)
    finish(thread)

    assert fake.calls == []


def test_a_burst_of_signals_for_one_timer_is_one_read() -> None:
    sink, fake, events = Sink(), host(), queue.Queue()
    timers = systemd.Timers(sink, fake, "a")
    timers.read()
    fake.calls.clear()
    fire(fake, "a.service")
    for _ in range(4):
        events.put((False, "a.service"))
    thread = run_serve(timers, events, backstop=60.0, fallback=60.0, debounce=0.1)

    assert wait_for(lambda: started(sink)["a"] == FIRED_ISO)
    time.sleep(0.3)
    finish(thread)

    assert len(fake.calls) == 2  # the timer and its service, once


def test_the_backstop_lists_every_timer_again_when_it_comes_due() -> None:
    sink, fake = Sink(), host()
    timers = systemd.Timers(sink, fake, "a, b")
    timers.read()
    fire(fake, "b.service")  # a change whose signal never arrived
    thread = run_serve(timers, queue.Queue(), backstop=0.05, fallback=60.0, debounce=0.01)

    assert wait_for(lambda: started(sink)["b"] == FIRED_ISO)
    finish(thread)


def test_a_dead_monitor_falls_back_to_the_short_listing_interval() -> None:
    sink, fake = Sink(), host()
    timers = systemd.Timers(sink, fake, "a")
    timers.read()
    fire(fake, "a.service")
    stop = threading.Event()
    thread = threading.Thread(
        target=systemd.serve,
        args=(timers, queue.Queue(), stop),
        kwargs={"healthy": lambda: False, "backstop": 60.0, "fallback": 0.05, "debounce": 0.01},
        daemon=True,
    )
    thread.start()

    assert wait_for(lambda: started(sink)["a"] == FIRED_ISO)
    stop.set()
    thread.join(timeout=2)


def test_closing_the_monitor_terminates_its_gdbus_child(tmp_path, monkeypatch) -> None:
    pidfile = tmp_path / "pid"
    fake = tmp_path / "gdbus"
    fake.write_text(f"#!/bin/sh\necho $$ > {pidfile}\necho line\nexec sleep 60\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    lines = systemd.monitor(user=False)
    assert next(lines) == "line\n"
    pid = int(pidfile.read_text())

    lines.close()

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
