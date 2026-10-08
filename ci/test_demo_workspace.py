"""The UI preview's synthetic workspace: the Board adapter `ci/preview.toml` names and the domains it lays out."""

from __future__ import annotations

from pathlib import Path

import demo_workspace
import tomllib

from starpulse.cli.demo import scrub

PREVIEW = Path(__file__).with_name("preview.toml")
NOW = 1_790_000_000.0
LANES = ["new", "ready", "waiting", "in_progress", "review", "needs_attention", "done", "completed", "archived"]


def _workflows() -> list[str]:
    runs = tomllib.loads(PREVIEW.read_text())["runs"]
    return [f"{r['name']}/{w}" for r in runs for ws in r["domains"].values() for w in ws]


def _machines() -> dict[str, dict]:
    return demo_workspace.board({"type": "demo_workspace"}, PREVIEW.parent).machines(lambda n: n, _workflows())


def test_the_preview_board_draws_a_real_workspaces_nine_lanes_in_order() -> None:
    board = _machines()["board"]

    assert [s["id"] for s in board["states"]] == LANES
    assert board["mainLine"] == LANES[:7]


def test_in_progress_opens_the_delivery_machine_and_at_least_three_more_lifecycle_machines() -> None:
    machines = _machines()

    assert machines["board"]["subflows"][0] == {
        "state": "in_progress",
        "flow": "delivery",
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
    assert actors and actors <= set(_workflows())


def _capture() -> dict:
    """The snapshot CI's server opens its stream with on `ci/preview.toml`: this structure, no task and no run."""
    machines = _machines()
    domains = [
        {"name": domain, "dags": [{"name": f"{r['name']}/{w}", "runSafe": False} for w in ws]}
        for r in tomllib.loads(PREVIEW.read_text())["runs"]
        for domain, ws in r["domains"].items()
    ]
    return {
        "now": NOW,
        "flows": [{"name": name, "machine": body, "agents": []} for name, body in machines.items()],
        "graphs": [*machines, "runs"],
        "domains": domains,
        "dags": [],
        "pools": [],
        "pulls": {},
        "settled": {},
        "suns": dict.fromkeys(LANES, 0.0),
        "boardUrl": None,
        "hint": None,
    }


def _flows(demo: dict) -> dict[str, dict]:
    return {f["name"]: f for f in demo["flows"]}


def test_the_demo_keeps_the_nine_lanes_and_fills_them_at_a_real_workspaces_scale() -> None:
    demo = scrub(_capture())
    board = _flows(demo)["board"]

    assert [s["id"] for s in board["machine"]["states"]] == LANES
    assert len(board["agents"]) >= 100
    assert {a["state"] for a in board["agents"]} == set(LANES[:7])
    assert {e["state"] for e in demo["settled"].values()} == {"completed", "archived"}


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
