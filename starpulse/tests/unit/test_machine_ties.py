"""How a lifecycle machine is entered: its ties, where it nests, when it was last active and what is stuck in it."""

import pytest

from starpulse.board_feed import BoardFeed
from starpulse.machine_ties import STUCK_S, derive, entries, page, rows

NOW = 1_000_000.0
HOUR = 3600.0
IP = "delivery"


@pytest.fixture(autouse=True)
def _now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.board_feed.time.time", lambda: NOW)


def _machine(*states: str, subflows: list[dict] | None = None, **extra: object) -> dict:
    """A machine of `states` in order, the first initial and the last final."""
    return {
        "states": [
            {"id": s, "name": s, "initial": i == 0, "final": i == len(states) - 1} for i, s in enumerate(states)
        ],
        "transitions": [],
        **({"subflows": subflows} if subflows else {}),
        **extra,
    }


def _link(state: str, flow: str, parent: str) -> dict:
    return {"state": state, "flow": flow, "exits": {}, "parent": parent, "when": f"{flow} applies"}


def _session(task: str, trail: list[tuple[str, float]]) -> dict:
    """A task's session whose trail is (state, seconds before NOW) oldest first."""
    steps = [{"state": s, "event": s.upper(), "at": NOW - ago} for s, ago in trail]
    return {"id": task, "task": task, "state": steps[-1]["state"], "trail": steps, "active": steps[-1]["at"]}


def _flows(sessions: dict[str, list[dict]] | None = None, launches: dict | None = None) -> list[dict]:
    """The Board, the In Progress `delivery` machine with `review` under its `pr_opened`, and the `audit` and `fix` skills."""
    sessions = sessions or {}
    board = _machine(
        "new",
        "in_progress",
        "done",
        subflows=[_link("in_progress", IP, "board")],
        **({"launches": launches} if launches else {}),
    )
    machines = {
        IP: _machine("start", "pr_opened", "merged", subflows=[_link("pr_opened", "review", IP)]),
        "review": _machine("triage", "fixed", "clean"),
        "audit": _machine("scan", "report", "filed"),
        "fix": _machine("diagnose", "patched", "closed"),
    }
    return [
        {"name": "board", "machine": board, "agents": []},
        *({"name": n, "machine": m, "agents": sessions.get(n, [])} for n, m in machines.items()),
    ]


def _derived(sessions: dict[str, list[dict]] | None = None, launches: dict | None = None) -> dict[str, dict]:
    return derive(_flows(sessions, launches), NOW)


def _tie(kind: str, machine: str | None, state: str | None, count: int | None, dag: str | None = None) -> dict:
    return {"kind": kind, "machine": machine, "state": state, "count": count, "dag": dag, "when": ""}


class TestTies:
    def test_a_declared_tie_names_the_machine_and_state_a_subflow_opens_from(self) -> None:
        review = _derived()["review"]["ties"]

        assert review == [{**_tie("declared", IP, "pr_opened", 0), "when": "review applies"}]

    def test_an_observed_tie_names_the_state_the_task_held_when_its_session_entered_with_a_count(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 3000), ("pr_opened", 1500), ("merged", 100)])],
            "audit": [_session("T1", [("scan", 1000)])],
        }

        assert _derived(sessions)["audit"]["ties"] == [_tie("observed", IP, "pr_opened", 1)]

    def test_each_task_that_entered_from_the_same_state_adds_one_to_the_count(self) -> None:
        sessions = {
            IP: [_session(t, [("start", 3000), ("pr_opened", 2000)]) for t in ("T1", "T2", "T3")],
            "audit": [_session(t, [("scan", 1000)]) for t in ("T1", "T2")],
        }

        assert _derived(sessions)["audit"]["ties"] == [_tie("observed", IP, "pr_opened", 2)]

    def test_a_session_entered_while_the_task_was_in_a_skill_machine_is_entered_from_that_machines_state(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000), ("pr_opened", 4000)])],
            "audit": [_session("T1", [("scan", 3000), ("report", 1000)])],
            "fix": [_session("T1", [("diagnose", 1000)])],
        }

        assert _derived(sessions)["fix"]["ties"] == [_tie("observed", "audit", "report", 1)]

    def test_a_session_matching_the_declared_tie_counts_on_it_instead_of_adding_an_observed_one(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 3000), ("pr_opened", 1500)])],
            "review": [_session("T1", [("triage", 1000)])],
        }

        assert _derived(sessions)["review"]["ties"] == [
            {**_tie("declared", IP, "pr_opened", 1), "when": "review applies"}
        ]

    def test_a_dag_launch_is_a_tie_naming_the_dag_and_no_machine(self) -> None:
        launches = {"ops/nightly": {"skill": "audit", "flow": None}}

        assert _derived(launches=launches)["audit"]["ties"] == [_tie("dag", None, None, None, "ops/nightly")]

    def test_a_launch_names_the_skill_when_its_flow_is_not_a_machine_here(self) -> None:
        launches = {
            "ops/nightly": {"skill": "audit", "flow": "elsewhere"},
            "ops/triage": {"skill": "x", "flow": "review"},
        }
        derived = _derived(launches=launches)

        assert [t["dag"] for t in derived["audit"]["ties"]] == ["ops/nightly"]
        assert [t["dag"] for t in derived["review"]["ties"] if t["kind"] == "dag"] == ["ops/triage"]

    def test_the_declared_tie_leads_then_the_most_observed_then_the_dag_launches(self) -> None:
        sessions = {
            IP: [_session(t, [("start", 3000), ("pr_opened", 2000)]) for t in ("T1", "T2", "T3")],
            "audit": [
                _session("T1", [("scan", 1000)]),
                _session("T2", [("scan", 1000)]),
                _session("T3", [("scan", 1000)]),
            ],
            "review": [_session("T1", [("triage", 900)])],
        }
        launches = {"ops/nightly": {"skill": "audit", "flow": None}}
        derived = _derived(sessions, launches)

        assert [t["kind"] for t in derived["audit"]["ties"]] == ["observed", "dag"]
        assert [(t["kind"], t["machine"], t["count"]) for t in derived["review"]["ties"]] == [
            ("declared", IP, 0),
            ("observed", "audit", 1),
        ]

    def test_a_machine_nothing_enters_has_no_ties(self) -> None:
        assert _derived()["audit"]["ties"] == []


class TestNesting:
    def test_a_machine_nests_under_the_machine_its_leading_tie_enters_it_from(self) -> None:
        derived = _derived()

        assert derived["review"]["parent"] == IP
        assert derived["review"]["depth"] == 1
        assert derived["audit"]["parent"] == IP

    def test_a_machine_entered_from_a_skill_machine_nests_below_it_with_its_chain(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000)])],
            "audit": [_session("T1", [("scan", 4000), ("report", 1000)])],
            "fix": [_session("T1", [("diagnose", 1000)])],
        }
        derived = _derived(sessions)

        assert derived["fix"]["parent"] == "audit"
        assert derived["fix"]["chain"] == ["audit"]
        assert derived["fix"]["depth"] == 2
        assert derived["audit"]["nested"] == ["fix"]
        assert derived[IP]["nested"] == ["review", "audit", "fix"]

    def test_a_loop_of_ties_breaks_to_the_in_progress_machine(self) -> None:
        sessions = {
            "audit": [_session("T1", [("scan", 3000), ("report", 2300)]), _session("T2", [("scan", 2000)])],
            "fix": [_session("T1", [("diagnose", 2000)]), _session("T2", [("diagnose", 3000), ("patched", 2300)])],
        }
        derived = _derived(sessions)

        assert (derived["audit"]["parent"], derived["fix"]["parent"]) == (IP, "audit")
        assert derived["fix"]["ties"][0] == _tie("observed", "audit", "report", 1)

    def test_the_in_progress_machine_has_no_parent_ties_or_depth(self) -> None:
        top = _derived()[IP]

        assert (top["parent"], top["ties"], top["depth"], top["chain"]) == (None, [], 0, [])


class TestActivity:
    def test_a_machine_is_last_active_when_its_newest_task_last_moved(self) -> None:
        sessions = {"audit": [_session("T1", [("scan", 900)]), _session("T2", [("scan", 500)])]}

        assert _derived(sessions)["audit"]["last"] == NOW - 500

    def test_a_machine_without_tasks_has_no_last_activity(self) -> None:
        assert _derived()["audit"]["last"] is None

    def test_a_machine_is_as_recent_as_the_newest_machine_nested_below_it(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000), ("pr_opened", 4000)])],
            "review": [_session("T1", [("triage", 60)])],
        }
        derived = _derived(sessions)

        assert derived["review"]["last"] == NOW - 60
        assert derived[IP]["last"] == NOW - 60

    def test_a_task_idle_past_two_hours_in_a_working_state_is_stuck_since_its_last_move(self) -> None:
        sessions = {"audit": [_session("T1", [("scan", STUCK_S + 600)])]}

        assert _derived(sessions)["audit"]["stuck"] == {
            "machine": "audit",
            "state": "scan",
            "since": NOW - STUCK_S - 600,
        }

    def test_a_task_at_the_two_hour_mark_or_in_a_final_state_is_not_stuck(self) -> None:
        sessions = {
            "audit": [_session("T1", [("scan", STUCK_S)]), _session("T2", [("scan", 9 * HOUR), ("filed", 8 * HOUR)])]
        }

        assert _derived(sessions)["audit"]["stuck"] is None

    def test_stuck_rolls_up_the_longest_stuck_task_from_every_machine_nested_below(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000), ("pr_opened", 4000)])],
            "review": [_session("T1", [("triage", 3 * HOUR)]), _session("T2", [("fixed", 5 * HOUR)])],
            "audit": [_session("T3", [("report", 2.5 * HOUR)])],
        }
        derived = _derived(sessions)
        longest = {"machine": "review", "state": "fixed", "since": NOW - 5 * HOUR}

        assert derived["review"]["stuck"] == longest
        assert derived[IP]["stuck"] == longest
        assert derived["audit"]["stuck"] == {"machine": "audit", "state": "report", "since": NOW - 2.5 * HOUR}


class TestSnapshot:
    def test_a_snapshot_carries_each_non_board_machines_derivation_and_leaves_the_board_alone(self) -> None:
        machines = {f["name"]: f["machine"] for f in _flows()}
        feed = BoardFeed(machines=machines)
        feed.move("audit", _session("T1", [("scan", STUCK_S + 60)]) | {"title": "T1", "model": "", "steps": 1})
        flows = {f["name"]: f for f in feed.snapshot()["flows"]}

        assert "ties" not in flows["board"]
        assert flows["audit"]["parent"] == IP
        assert flows["audit"]["stuck"]["state"] == "scan"
        assert flows["review"]["ties"][0]["kind"] == "declared"


def _ranked(lasts: dict[str, float | None], parent: str = IP) -> dict[str, dict]:
    """The derivation of machines entered from `parent`, each with the given rolled-up `last`."""
    return {IP: {"parent": None, "last": NOW}, **{n: {"parent": parent, "last": t} for n, t in lasts.items()}}


class TestRows:
    def test_rows_are_the_machines_entered_from_the_open_one_newest_activity_first(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000), ("pr_opened", 4000)])],
            "review": [_session("T1", [("triage", 60)])],
            "audit": [_session("T2", [("scan", 500)])],
            "fix": [_session("T3", [("diagnose", 900)])],
        }

        assert rows(_derived(sessions), IP) == ["review", "audit", "fix"]

    def test_a_machine_nested_below_a_row_is_not_a_row_of_the_level_above(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000)])],
            "audit": [_session("T1", [("scan", 4000), ("report", 1000)])],
            "fix": [_session("T1", [("diagnose", 800)])],
        }
        derived = _derived(sessions)

        assert rows(derived, IP) == ["audit", "review"]
        assert rows(derived, "audit") == ["fix"]

    def test_machines_with_the_same_activity_rank_by_name_and_those_with_none_come_last(self) -> None:
        derived = _ranked({"zeta": NOW - 5, "alpha": NOW - 5, "idle": None, "mid": NOW - 50})

        assert rows(derived, IP) == ["alpha", "zeta", "mid", "idle"]


class TestPage:
    def test_a_page_is_the_next_limit_rows_older_than_the_cursor_and_says_whether_more_remain(self) -> None:
        derived = _ranked({f"m{i}": NOW - 100 * i for i in range(1, 6)})

        first = page(derived, IP, before=None, limit=2)
        second = page(derived, IP, before=derived[first[0][-1]]["last"], limit=2)
        third = page(derived, IP, before=derived[second[0][-1]]["last"], limit=2)

        assert first == (["m1", "m2"], True)
        assert second == (["m3", "m4"], True)
        assert third == (["m5"], False)

    def test_machines_sharing_the_boundary_activity_travel_together_so_no_page_skips_or_repeats_one(self) -> None:
        derived = _ranked({"a": NOW - 10, "b": NOW - 20, "c": NOW - 20, "d": NOW - 20, "e": NOW - 30})

        first, more = page(derived, IP, before=None, limit=2)
        rest, _ = page(derived, IP, before=derived[first[-1]]["last"], limit=2)

        assert (first, more) == (["a", "b", "c", "d"], True)
        assert rest == ["e"]

    def test_machines_with_no_activity_page_as_the_last_group(self) -> None:
        derived = _ranked({"a": NOW - 10, "x": None, "y": None})

        first, _ = page(derived, IP, before=None, limit=1)
        rest = page(derived, IP, before=derived[first[-1]]["last"], limit=1)

        assert (first, rest) == (["a"], (["x", "y"], False))

    def test_a_level_with_nothing_entered_from_it_has_no_rows(self) -> None:
        assert page(_ranked({"a": NOW}), "a", before=None, limit=20) == ([], False)


def _entries(sessions: dict[str, list[dict]], launches: dict | None = None, span: float = 24 * HOUR) -> list[dict]:
    flows = _flows(sessions, launches)
    return entries(flows, derive(flows, NOW), NOW, span)


class TestEntries:
    def test_an_entry_has_its_time_and_the_state_the_machine_was_entered_from(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 3000), ("pr_opened", 1500)])],
            "audit": [_session("T1", [("scan", 1000), ("report", 500)])],
        }

        assert _entries(sessions) == [
            {
                "at": NOW - 1000,
                "machine": "audit",
                "row": "audit",
                "from": {"machine": IP, "state": "pr_opened"},
                "dag": None,
            }
        ]

    def test_an_entry_into_a_nested_machine_counts_on_the_row_above_it(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 5000)])],
            "audit": [_session("T1", [("scan", 4000), ("report", 1000)])],
            "fix": [_session("T1", [("diagnose", 800)])],
        }
        found = {e["machine"]: e for e in _entries(sessions)}

        assert found["fix"]["row"] == "audit"
        assert found["fix"]["from"] == {"machine": "audit", "state": "report"}
        assert found["audit"]["row"] == "audit"

    def test_an_entry_by_a_dag_launch_names_the_dag_and_no_state(self) -> None:
        launches = {"ops/nightly": {"skill": "audit", "flow": None}}
        run = {"id": "run-1", "state": "scan", "trail": [{"state": "scan", "event": "SCAN", "at": NOW - 600}]}
        run["active"] = NOW - 600

        assert _entries({"audit": [run]}, launches) == [
            {"at": NOW - 600, "machine": "audit", "row": "audit", "from": None, "dag": "ops/nightly"}
        ]

    def test_entries_run_oldest_first_and_leave_out_the_in_progress_machine_and_anything_past_the_span(self) -> None:
        sessions = {
            IP: [_session("T1", [("start", 90_000), ("pr_opened", 80_000)])],
            "review": [_session("T1", [("triage", 70_000)])],
            "audit": [_session("T2", [("scan", 100_000)]), _session("T3", [("scan", 300)])],
        }

        assert [(e["machine"], e["at"]) for e in _entries(sessions)] == [("review", NOW - 70_000), ("audit", NOW - 300)]


def _full(session: dict) -> dict:
    return session | {"title": session["task"], "model": "", "steps": len(session["trail"])}


def _crowded_feed(extra: int = 24) -> BoardFeed:
    """The fixture machines plus `extra` more, `m00` the most and `m<extra-1>` the least recently active, each entered
    from the In Progress machine by a task of its own."""
    machines = {f["name"]: f["machine"] for f in _flows()}
    machines |= {f"m{i:02d}": _machine("a", "b") for i in range(extra)}
    feed = BoardFeed(machines=machines)
    for i in range(extra):
        feed.move(f"m{i:02d}", _full(_session(f"X{i}", [("a", 600 + 10 * i)])))
    return feed


class TestFeedPages:
    def test_the_snapshot_carries_the_first_twenty_rows_of_the_in_progress_machine_and_whether_more_follow(
        self,
    ) -> None:
        snapshot = _crowded_feed().snapshot()

        assert snapshot["machinePage"] == {
            "open": IP,
            "machines": [f"m{i:02d}" for i in range(20)],
            "more": True,
        }

    def test_the_machines_route_pages_by_open_machine_cursor_and_limit_with_no_overlap_or_gap(self) -> None:
        feed = _crowded_feed()
        seen: list[str] = []
        before = None
        for _ in range(10):
            got = feed.machine_rows(IP, before, 10)
            seen += [m["name"] for m in got["machines"]]
            if not got["more"]:
                break
            before = got["machines"][-1]["last"]
        rows_ = [m for m in seen if m.startswith("m")]

        assert rows_ == [f"m{i:02d}" for i in range(24)]
        assert len(seen) == len(set(seen)) == 24 + 3

    def test_a_page_holds_each_machine_whole_with_its_derivation(self) -> None:
        got = _crowded_feed().machine_rows(IP, None, 1)

        assert got["open"] == IP
        assert got["machines"][0]["agents"][0]["task"] == "X0"
        assert got["machines"][0]["parent"] == IP
        assert got["machines"][0]["machine"]["states"][0]["id"] == "a"

    def test_a_level_below_a_row_pages_the_machines_entered_from_it(self) -> None:
        feed = BoardFeed(machines={f["name"]: f["machine"] for f in _flows()})
        feed.move(IP, _full(_session("T1", [("start", 5000)])))
        feed.move("audit", _full(_session("T1", [("scan", 4000), ("report", 1000)])))
        feed.move("fix", _full(_session("T1", [("diagnose", 800)])))

        assert [m["name"] for m in feed.machine_rows("audit", None, 20)["machines"]] == ["fix"]

    def test_the_default_open_machine_is_the_in_progress_one_and_an_unknown_one_has_no_page(self) -> None:
        feed = _crowded_feed(3)

        assert feed.machine_rows(None, None, 20)["open"] == IP
        assert feed.machine_rows("nope", None, 20) is None


class TestFeedStrip:
    def test_the_snapshot_lists_the_last_24_hours_of_machine_entries_with_the_row_each_lands_on(self) -> None:
        feed = BoardFeed(machines={f["name"]: f["machine"] for f in _flows()})
        feed.move(IP, _full(_session("T1", [("start", 5000)])))
        feed.move("audit", _full(_session("T1", [("scan", 4000), ("report", 1000)])))
        feed.move("fix", _full(_session("T1", [("diagnose", 800)])))
        feed.move("review", _full(_session("T9", [("triage", 25 * HOUR)])))
        strip = feed.snapshot()["machineStrip"]

        assert [(e["machine"], e["row"], e["at"]) for e in strip["entries"]] == [
            ("audit", "audit", NOW - 4000),
            ("fix", "audit", NOW - 800),
        ]
