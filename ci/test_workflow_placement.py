"""Where each workflow job runs: pull-request validation on the validate lane, tag publishing on hosted runners."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
VALIDATE_LANE = ["self-hosted", "validate"]
#: The label only the Unraid farm slots carry: the hardware the latency budget was calibrated on.
TOWER_LANE = ["self-hosted", "validate", "tower"]
HOSTED = "ubuntu-latest"


def job(workflow: str, name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][name]


@pytest.mark.parametrize(
    ("workflow", "name"),
    [("ci.yml", "python"), ("ci.yml", "web"), ("ci.yml", "api-types"), ("ui-preview.yml", "render"), ("ui-preview.yml", "leak-scan")],
)
def test_pull_request_job_runs_on_the_validate_lane(workflow, name):
    assert job(workflow, name)["runs-on"] == VALIDATE_LANE


def test_release_build_runs_on_the_validate_lane_for_a_pull_request_and_hosted_for_a_tag():
    runs_on = job("release.yml", "build")["runs-on"]
    match = re.fullmatch(
        r"\$\{\{ startsWith\(github\.ref, 'refs/tags/v'\) && '([^']+)' \|\| fromJSON\('([^']+)'\) \}\}", runs_on
    )
    assert match, runs_on
    tag_runner, pull_request_runner = match.groups()
    assert tag_runner == HOSTED
    assert json.loads(pull_request_runner) == VALIDATE_LANE


@pytest.mark.parametrize("name", ["github-release", "pypi"])
def test_publishing_job_runs_on_a_hosted_runner(name):
    assert job("release.yml", name)["runs-on"] == HOSTED


@pytest.mark.parametrize(
    ("workflow", "name"),
    [
        ("ci.yml", "web"),
        ("ci.yml", "api-types"),
        ("release.yml", "build"),
        ("release.yml", "soak"),
        ("ui-preview.yml", "render"),
    ],
)
def test_node_is_installed_before_pnpm(workflow, name):
    """`pnpm/action-setup` installs pnpm with the runner's `npm`, which fails under the system Node of a validate runner."""
    uses = [step["uses"].split("@")[0] for step in job(workflow, name)["steps"] if "uses" in step]
    assert uses.index("actions/setup-node") < uses.index("pnpm/action-setup")


def needs(workflow: str, name: str) -> list[str]:
    declared = job(workflow, name).get("needs", [])
    return [declared] if isinstance(declared, str) else declared


def test_release_soak_runs_on_tower_after_the_build_and_gates_both_publishing_jobs():
    """A red soak publishes nothing: the GitHub Release and PyPI both wait for it, and it waits for a build that passed."""
    assert job("release.yml", "soak")["runs-on"] == TOWER_LANE
    assert "build" in needs("release.yml", "soak")
    assert "soak" in needs("release.yml", "github-release")
    assert "soak" in needs("release.yml", "pypi")


def test_release_soak_runs_for_a_tag_or_a_dispatch_and_publishing_only_for_a_tag_push():
    """A pull request never takes a Tower slot for hours, and a dispatch on a tag's ref publishes nothing."""
    assert job("release.yml", "soak")["if"] == "github.event_name != 'pull_request'"
    assert job("release.yml", "github-release")["if"] == "github.event_name == 'push'"
    assert job("release.yml", "pypi")["if"] == "github.event_name == 'push'"


def test_release_soak_holds_the_duration_input_four_hours_by_default_and_reports_what_it_saw():
    document = yaml.safe_load((WORKFLOWS / "release.yml").read_text())
    duration = document[True]["workflow_dispatch"]["inputs"]["duration"]
    soak = job("release.yml", "soak")
    run = next(step for step in soak["steps"] if "bench/soak.py" in step.get("run", ""))
    upload = next(step for step in soak["steps"] if step.get("uses", "").startswith("actions/upload-artifact"))

    assert duration["default"] == "4h"
    assert run["env"]["DURATION"] == "${{ inputs.duration || '4h' }}"  # a tag push has no inputs
    assert '--duration "$DURATION"' in run["run"]
    assert "--report" in run["run"]  # the exit status is the step's: no `|| true`, no `continue-on-error`
    assert "||" not in run["run"]
    assert not run.get("continue-on-error")
    assert upload["if"] == "always()"  # a failed or timed-out soak is the report most worth reading
    assert soak["timeout-minutes"] > 4 * 60  # past the hold, with the build and the server's start


def test_release_soak_queues_behind_a_running_one_rather_than_cancelling_it():
    """A 4 hour hold is not restarted by the next run: one holds a farm slot, the next waits."""
    concurrency = job("release.yml", "soak")["concurrency"]
    assert concurrency["group"]
    assert concurrency["cancel-in-progress"] is False


def test_trantor_tier_policy_gates_the_green_dispatch():
    """A commit failing trantor's tier policy fails every bump that pins it, so it must not dispatch as green."""
    run = next(step["run"] for step in job("ci.yml", "tier-policy")["steps"] if "run" in step)
    assert "ci/trantor_tier_policy.py" in run
    assert "tier-policy" in job("ci.yml", "dispatch")["needs"]


def test_trantor_tests_of_this_package_gate_the_green_dispatch():
    """A commit failing trantor's tests of this package fails every bump that pins it, so it must not dispatch as green."""
    contract = job("ci.yml", "trantor-contract")
    checkouts = [step["with"] for step in contract["steps"] if step.get("uses", "").startswith("actions/checkout")]
    runs = "\n".join(step["run"] for step in contract["steps"] if "run" in step)
    assert contract["runs-on"] == VALIDATE_LANE
    assert {"repository": "trantor-org/trantor", "path": ".trantor"}.items() <= checkouts[0].items()
    assert checkouts[1]["path"] == ".trantor/starpulse"  # this tree in the submodule's place
    assert "make test-changed FILES=starpulse CI=1" in runs
    assert "trantor-contract" in job("ci.yml", "dispatch")["needs"]


def test_main_follow_submit_runs_on_ai_vm_1_and_never_for_a_fork():
    """The submit reaches trantor's Dagu from the host, and this repository is public: a fork's close must not run it.

    The file is read from the base branch under `pull_request_target`, so a fork cannot edit the condition away.
    """
    document = yaml.safe_load((WORKFLOWS / "main-follow-on-close.yml").read_text())
    follow = document["jobs"]["follow"]

    assert document[True] == {"pull_request_target": {"types": ["closed"]}}
    assert follow["runs-on"] == ["self-hosted", "ai-vm-1"]
    assert follow["if"] == "github.event.pull_request.head.repo.full_name == github.repository"
