"""The UI preview's synthetic workspace: the Board adapter `ci/preview.toml` names and the domains it lays out."""

from __future__ import annotations

from pathlib import Path

import demo_workspace
import tomllib

from starpulse._internal.cli.demo import scrub

PREVIEW = Path(__file__).with_name("preview.toml")
NOW = 1_790_000_000.0
LANES = ["new", "ready", "waiting", "in_progress", "review", "needs_attention", "done", "archived"]


def _domain_workflows(value: object) -> list[str]:
    """Workflow names under a domain: a flat list, or the union of nested process lists."""
    if isinstance(value, list) and all(isinstance(w, str) for w in value):
        return list(value)
    if isinstance(value, dict) and all(isinstance(ws, list) for ws in value.values()):
        return [w for ws in value.values() for w in ws]
    return []


def _workflows() -> list[str]:
    runs = tomllib.loads(PREVIEW.read_text())["runs"]
    return [f"{r['name']}/{w}" for r in runs for ws in r["domains"].values() for w in _domain_workflows(ws)]


def _board():
    return demo_workspace.board({"type": "demo_workspace"}, PREVIEW.parent)


def _machines() -> dict[str, dict]:
    return _board().machines(lambda n: n, _workflows())


def test_the_preview_board_serves_each_lanes_declared_type_for_the_column_headers() -> None:
    states = _machines()["board"]["states"]

    assert {s["id"]: s["role"] for s in states} == {
        "new": "initial",
        "ready": "waiting_on_fact",
        "waiting": "waiting_on_fact",
        "in_progress": "resting",
        "review": "waiting_on_fact",
        "needs_attention": "waiting_on_person",
        "done": "final",
        "archived": "final",
    }


def test_the_preview_board_draws_a_real_workspaces_eight_lanes_in_order() -> None:
    board = _machines()["board"]

    assert [s["id"] for s in board["states"]] == LANES
    assert board["mainLine"] == ["new", "ready", "in_progress", "review"]


def test_the_preview_board_declares_the_tiers_the_star_map_draws_it_in() -> None:
    board = _machines()["board"]

    assert board["tiers"] == [
        ["new"],
        ["ready", "waiting"],
        ["needs_attention"],
        ["in_progress"],
        ["review"],
        ["done", "archived"],
    ]
    assert sorted(state for tier in board["tiers"] for state in tier) == sorted(LANES)


def test_the_preview_board_reopens_done_to_every_open_lane_and_still_draws_done_as_an_end() -> None:
    board = _machines()["board"]
    reopened = {t["target"] for t in board["transitions"] if t["source"] == "done"}

    assert reopened == {"ready", "waiting", "in_progress", "review", "needs_attention"}
    assert {s["id"]: s.get("final", False) for s in board["states"]}["done"] is True


def test_in_progress_opens_the_delivery_machine_and_at_least_three_more_lifecycle_machines() -> None:
    machines = _machines()

    assert machines["board"]["submachines"][0] == {
        "state": "in_progress",
        "machine": "delivery",
        "exits": {},
        "parent": "board",
        "when": "",
    }
    assert len(set(machines) - {"board", "delivery"}) >= 3


def test_the_preview_lays_out_five_domains_of_at_least_thirty_workflows() -> None:
    runs = tomllib.loads(PREVIEW.read_text())["runs"]

    assert sum(len(r["domains"]) for r in runs) == 5
    assert len(_workflows()) >= 30


def test_the_board_names_only_workflows_the_preview_lists() -> None:
    board = _machines()["board"]

    actors = {w["actor"] for ws in board["writers"].values() for w in ws}
    assert actors - {"operator", "agent"} <= set(_workflows())
    assert actors & set(_workflows())


def _capture() -> dict:
    """The snapshot CI's server opens its stream with on `ci/preview.toml`: this structure, no task and no run."""
    machines = _machines()
    domains = [
        {
            "name": domain,
            "dags": [{"name": f"{r['name']}/{w}", "runSafe": False} for w in _domain_workflows(ws)],
        }
        for r in tomllib.loads(PREVIEW.read_text())["runs"]
        for domain, ws in r["domains"].items()
    ]
    return {
        "now": NOW,
        "roles": _board().roles.wire(),
        "flows": [{"name": name, "machine": body, "agents": []} for name, body in machines.items()],
        "graphs": [*machines, "runs"],
        "domains": domains,
        "dags": [],
        "pools": [],
        "pulls": {},
        "settled": {},
        "boardUrl": None,
        "hint": None,
    }


def _flows(demo: dict) -> dict[str, dict]:
    return {f["name"]: f for f in demo["flows"]}


def test_the_demo_keeps_the_eight_lanes_and_fills_them_at_a_real_workspaces_scale() -> None:
    demo = scrub(_capture())
    board = _flows(demo)["board"]

    assert [s["id"] for s in board["machine"]["states"]] == LANES
    assert len(board["agents"]) >= 100
    assert {a["state"] for a in board["agents"]} == set(LANES[:7])
    assert {e["state"] for e in demo["settled"].values()} == {"archived"}


def test_the_demo_holds_done_tasks_older_than_a_day_so_the_page_shows_only_the_last_day() -> None:
    done = [a for a in _flows(scrub(_capture()))["board"]["agents"] if a["state"] == "done"]

    old = [a for a in done if "entered" in a and a["entered"] < NOW - 86400]
    assert old and len(done) - len(old) >= 10


def test_the_demo_files_new_tasks_that_morning_so_the_new_lane_counts_them() -> None:
    board = _flows(scrub(_capture()))["board"]

    new = [a for a in board["agents"] if a["state"] == "new"]
    assert len(new) >= 30
    assert all(NOW - 6 * 3600 <= a.get("created", 0) <= NOW for a in new)


def test_the_demo_places_sessions_on_the_delivery_machine_and_on_at_least_three_lifecycle_machines() -> None:
    flows = _flows(scrub(_capture()))

    busy = {name for name, f in flows.items() if name != "board" and f["agents"]}
    assert "delivery" in busy
    assert len(busy) >= 4
    assert all(a["trail"] for name in busy for a in flows[name]["agents"])


def test_the_demo_seeds_runs_on_every_domain_and_at_least_six_pools() -> None:
    demo = scrub(_capture())

    ran = {d["name"] for d in demo["dags"]}
    assert all(any(x["name"] in ran for x in domain["dags"]) for domain in demo["domains"])
    assert len(demo["pools"]) >= 6


def test_the_demo_opens_with_recent_lines_from_finished_runs_and_session_moves() -> None:
    demo = scrub(_capture())

    finished = [d for d in demo["dags"] if d.get("finishedAt")]
    moves = [
        t for f in demo["flows"] if f["name"] != "board" for a in f["agents"] for t in a["trail"] if t["at"] <= NOW
    ]
    assert len(finished) >= 10
    assert len(moves) >= 20
