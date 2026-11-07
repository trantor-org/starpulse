"""The post-deploy UI smoke: its verdict holds the 50 ms and 500 ms budgets, and its modals are ones the page draws."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _smoke():
    spec = importlib.util.spec_from_file_location("ui_smoke", ROOT / "bench" / "ui_smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_modal_over_500_ms_p95_fails_the_run() -> None:
    smoke = _smoke()
    result = smoke.verdict({"Task view": [100.0, 120.0, 501.0]}, {}, [], 3.0)
    assert result["ok"] is False
    assert result["failures"] == ["Task view: p95 501.0 ms over 500 ms"]


def test_an_api_route_over_50_ms_p95_fails_the_run() -> None:
    smoke = _smoke()
    result = smoke.verdict({"New task": [10.0]}, {"/api/task/*": [10.0, 51.0]}, [], 3.0)
    assert result["failures"] == ["/api/task/*: p95 51.0 ms over 50 ms"]


def test_a_modal_with_no_sample_and_a_problem_fail_the_run() -> None:
    smoke = _smoke()
    result = smoke.verdict({"New task": []}, {}, ["/api/scheduler: untimed request"], 3.0)
    assert result["failures"] == ["New task: no sample", "/api/scheduler: untimed request"]


def test_samples_within_both_budgets_pass() -> None:
    smoke = _smoke()
    result = smoke.verdict({"New task": [20.0, 500.0]}, {"/api/harnesses": [50.0]}, [], 3.0)
    assert result["ok"] is True
    assert result["modals"]["New task"]["p95_ms"] == 500.0


def test_routes_group_ids_and_hashes() -> None:
    smoke = _smoke()
    assert smoke.route("/api/task/TASK-12") == "/api/task/*"
    assert smoke.route("/api/events/body/" + "a" * 40) == "/api/events/body/*"
    assert smoke.route("/api/scheduler") == "/api/scheduler"


def test_every_modal_the_smoke_opens_is_a_dialog_the_page_draws() -> None:
    smoke = _smoke()
    web = "\n".join(
        path.read_text() for path in (ROOT / "starpulse" / "web" / "src").rglob("*.tsx") if ".test." not in path.name
    )
    names = {
        "Task view",
        "New task",
        "Start-session confirm",
        "Connect a tracker",
        "DAG modal",
        "In Progress drill-in",
        "Admin theme confirm",
    }
    assert {modal.name for modal in smoke.MODALS} == names
    for modal in smoke.MODALS:
        literal = re.sub(r"[\^$]|\[A-Z\]\+-\\d\+ |\.\+", "", modal.label).strip()
        assert literal == "" or literal in web, modal.name
