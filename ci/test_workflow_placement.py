"""Where each workflow job runs: pull-request validation on the validate lane, tag publishing on hosted runners."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
VALIDATE_LANE = ["self-hosted", "validate"]
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
    [("ci.yml", "web"), ("ci.yml", "api-types"), ("release.yml", "build"), ("ui-preview.yml", "render")],
)
def test_node_is_installed_before_pnpm(workflow, name):
    """`pnpm/action-setup` installs pnpm with the runner's `npm`, which fails under the system Node of a validate runner."""
    uses = [step["uses"].split("@")[0] for step in job(workflow, name)["steps"] if "uses" in step]
    assert uses.index("actions/setup-node") < uses.index("pnpm/action-setup")


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
