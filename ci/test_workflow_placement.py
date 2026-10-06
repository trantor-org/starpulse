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
    [("ci.yml", "python"), ("ci.yml", "web"), ("ui-preview.yml", "render"), ("ui-preview.yml", "leak-scan")],
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
