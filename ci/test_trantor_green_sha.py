"""Which trantor main commit the trantor-contract job tests: the newest one whose CI passed, not the tip."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from trantor_green_sha import newest_green_sha

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


def run(sha: str, conclusion: str | None, created_at: str) -> dict:
    return {"head_sha": sha, "conclusion": conclusion, "created_at": created_at}


def test_a_green_tip_is_the_sha_chosen(capsys):
    response = {
        "workflow_runs": [run("tip", "success", "2026-10-12T20:00:00Z"), run("old", "success", "2026-10-12T19:00:00Z")]
    }
    assert newest_green_sha(response) == "tip"
    assert "tip" in capsys.readouterr().err


def test_a_red_or_unfinished_tip_selects_the_previous_green_sha():
    response = {
        "workflow_runs": [
            run("tip", "failure", "2026-10-12T20:00:00Z"),
            run("running", None, "2026-10-12T19:30:00Z"),
            run("green", "success", "2026-10-12T19:00:00Z"),
            run("older-green", "success", "2026-10-12T18:00:00Z"),
        ]
    }
    assert newest_green_sha(response) == "green"


@pytest.mark.parametrize(
    "runs", [[], [run("a", "failure", "2026-10-12T20:00:00Z"), run("b", "cancelled", "2026-10-12T19:00:00Z")]]
)
def test_no_green_sha_in_the_lookback_fails_with_a_message(runs):
    with pytest.raises(SystemExit, match="nothing green to test against"):
        newest_green_sha({"workflow_runs": runs})


def test_the_job_checks_out_the_sha_the_selector_printed():
    steps = yaml.safe_load(CI.read_text())["jobs"]["trantor-contract"]["steps"]
    pick = next(step for step in steps if "ci/trantor_green_sha.py" in step.get("run", ""))
    checkout = next(step for step in steps if step.get("with", {}).get("repository") == "trantor-org/trantor")
    assert checkout["with"]["ref"] == f"${{{{ steps.{pick['id']}.outputs.sha }}}}"
    assert steps.index(pick) < steps.index(checkout)
