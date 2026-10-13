"""Where each workflow job runs: pull-request validation on the validate lane, tag publishing on hosted runners."""

from __future__ import annotations

import json
import re
import subprocess
import time
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
    [
        ("ci.yml", "python-shard"),
        ("ci.yml", "python"),
        ("ci.yml", "web"),
        ("ci.yml", "api-types"),
        ("ci.yml", "static-checks"),
        ("ui-preview.yml", "render"),
        ("ui-preview.yml", "leak-scan"),
    ],
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
        ("ci.yml", "static-checks"),
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
    """A pull request or a merge-queue candidate never takes a Tower slot for hours, and a dispatch on a tag's ref publishes nothing."""
    assert job("release.yml", "soak")["if"] == (
        "github.event_name != 'pull_request' && github.event_name != 'merge_group'"
    )
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


def root_checkouts() -> list[tuple[str, dict]]:
    """Every actions/checkout step that fills the runner's workspace root, as (workflow/job, its `with`)."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, body in yaml.safe_load(path.read_text())["jobs"].items():
            for step in body.get("steps", []):
                options = step.get("with", {})
                if step.get("uses", "").startswith("actions/checkout@") and "path" not in options:
                    found.append((f"{path.name}/{name}", options))
    return found


def test_every_workspace_root_checkout_selects_the_full_tree():
    """A runner's workspace outlives its job: a sparse root checkout leaves core.sparseCheckout=true, which the next
    job's `git sparse-checkout disable` cannot clear, so that job gets a tree missing pyproject.toml and starpulse/web.
    `/*` in non-cone mode overwrites the stale pattern, healing a workspace an earlier sparse checkout poisoned."""
    checkouts = root_checkouts()
    assert checkouts
    for where, options in checkouts:
        assert options.get("sparse-checkout") == "/*", where
        assert options.get("sparse-checkout-cone-mode") is False, where


def test_trantor_tier_policy_gates_every_merge():
    """A commit failing trantor's tier policy fails every bump that pins it, so it must not reach main."""
    run = next(step["run"] for step in job("ci.yml", "tier-policy")["steps"] if "run" in step)
    assert "ci/trantor_tier_policy.py" in run
    assert ("ci.yml", "tier-policy") in REQUIRED_CHECKS


def test_trantor_tests_of_this_package_gate_every_merge():
    """A commit failing trantor's tests of this package fails every bump that pins it, so it must not reach main."""
    contract = job("ci.yml", "trantor-contract")
    checkouts = [step.get("with", {}) for step in contract["steps"] if step.get("uses", "").startswith("actions/checkout")]
    runs = "\n".join(step["run"] for step in contract["steps"] if "run" in step)
    assert contract["runs-on"] == VALIDATE_LANE
    assert checkouts[0]["sparse-checkout"] == "/*"  # a sparse root checkout empties every later job on the runner
    assert {"repository": "trantor-org/trantor", "path": ".trantor"}.items() <= checkouts[1].items()
    assert checkouts[2]["path"] == ".trantor/starpulse"  # this tree in the submodule's place
    assert "make test-changed FILES=starpulse CI=1" in runs
    assert ("ci.yml", "trantor-contract") in REQUIRED_CHECKS


#: Every ci.yml job but `dispatch`: the jobs that test a tree.
TEST_JOBS = ["python-shard", "python", "ic", "web", "api-types", "public-names", "tier-policy", "static-checks", "trantor-contract"]


@pytest.mark.parametrize("name", TEST_JOBS)
def test_a_push_to_main_runs_no_test_job(name):
    """Main moves only through the merge queue, which already tested the pushed commit (its candidate)."""
    assert "github.event_name != 'push'" in job("ci.yml", name)["if"]


def test_every_ci_job_but_dispatch_is_a_test_job():
    jobs = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]
    assert sorted(jobs) == sorted([*TEST_JOBS, "dispatch"])


def test_the_push_dispatch_waits_on_no_test_job():
    """Its test jobs skip on a push, and a job needing a skipped job is skipped; trantor re-checks the queue run."""
    assert "needs" not in job("ci.yml", "dispatch")


STATIC_SCRIPT = WORKFLOWS.parents[1] / "ci/static_checks.sh"


def test_static_checks_runs_every_check_the_four_short_jobs_ran():
    """ic, public-names, api-types and tier-policy share one job so a merge-queue run starts four fewer validate jobs."""
    script = STATIC_SCRIPT.read_text()
    runs = "\n".join(step["run"] for step in job("ci.yml", "static-checks")["steps"] if "run" in step)
    assert "ci/static_checks.sh" in runs
    for command in (
        "uv sync --locked --no-group hub",  # ic: an environment without the hub extras
        "ci/ic_imports.py",
        "ci/public_names.py",
        "python -m starpulse.contracts.api",  # api-types: regenerate both outputs, fail on a diff
        "pnpm --dir starpulse/web run gen:types",
        "git diff --exit-code -- starpulse/api.schema.json starpulse/web/src/api/types.gen.ts",
        "ci/trantor_tier_policy.py .trantor/lib/linting/check_config_checks/tier_policy.py",  # tier-policy
    ):
        assert command in script, command


def test_static_checks_checks_out_trantor_for_the_tier_policy():
    steps = job("ci.yml", "static-checks")["steps"]
    checkouts = [step.get("with", {}) for step in steps if step.get("uses", "").startswith("actions/checkout")]
    assert {"repository": "trantor-org/trantor", "path": ".trantor"}.items() <= checkouts[1].items()


def stub_tools(tmp_path, *, delay: float = 0.0) -> Path:
    """A directory holding `uv`, `pnpm` and `git` stubs that log each call and fail one whose arguments hold $FAIL_ON."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("uv", "pnpm", "git"):
        stub = bin_dir / tool
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "{tool} $*" >> "$CALLS"\n'
            f"sleep {delay}\n"
            '[ -n "${FAIL_ON:-}" ] && [[ "$*" == *"$FAIL_ON"* ]] && exit 1\n'
            "exit 0\n"
        )
        stub.chmod(0o755)
    return bin_dir


def run_static_checks(tmp_path, *, fail_on: str = "", delay: float = 0.0) -> subprocess.CompletedProcess:
    calls = tmp_path / "calls"
    calls.touch()
    env = {
        "PATH": f"{stub_tools(tmp_path, delay=delay)}:/usr/bin:/bin",
        "CALLS": str(calls),
        "FAIL_ON": fail_on,
        "RUNNER_TEMP": str(tmp_path),
    }
    return subprocess.run(
        ["bash", str(STATIC_SCRIPT)], env=env, cwd=tmp_path, capture_output=True, text=True, check=False
    )


def test_static_checks_passes_when_every_check_passes(tmp_path):
    assert run_static_checks(tmp_path).returncode == 0


@pytest.mark.parametrize(
    ("fail_on", "name"),
    [
        ("ci/ic_imports.py", "ic"),
        ("ci/public_names.py", "public-names"),
        ("gen:types", "api-types"),
        ("ci/trantor_tier_policy.py", "tier-policy"),
    ],
)
def test_static_checks_fails_naming_the_failed_check_and_still_runs_the_others(tmp_path, fail_on, name):
    result = run_static_checks(tmp_path, fail_on=fail_on)
    assert result.returncode == 1
    assert re.findall(r"static check failed: (\S+)", result.stdout) == [name]
    calls = (tmp_path / "calls").read_text()
    assert all(command in calls for command in ("ci/ic_imports.py", "ci/public_names.py", "ci/trantor_tier_policy.py"))


def test_static_checks_runs_its_checks_concurrently(tmp_path):
    """Run in sequence, the stubbed calls would take their summed delay; the job's wall time is the longest check's."""
    started = time.monotonic()
    result = run_static_checks(tmp_path, delay=0.6)
    calls = len((tmp_path / "calls").read_text().splitlines())
    assert result.returncode == 0
    assert time.monotonic() - started < 0.6 * calls * 0.75  # the longest check is half the calls


def test_main_follow_submit_runs_on_the_merge_event_lane_and_never_for_a_fork():
    """The submit reaches trantor's Dagu from the host, and this repository is public: a fork's close must not run it.

    The file is read from the base branch under `pull_request_target`, so a fork cannot edit the condition away.
    The merge-event lane is one runner no CI job targets, so the close never queues behind the same merge's jobs.
    """
    document = yaml.safe_load((WORKFLOWS / "main-follow-on-close.yml").read_text())
    follow = document["jobs"]["follow"]

    assert document[True] == {"pull_request_target": {"types": ["closed"]}}
    assert follow["runs-on"] == ["self-hosted", "merge-event"]
    assert follow["if"] == "github.event.pull_request.head.repo.full_name == github.repository"


def test_only_the_close_submit_targets_the_merge_event_lane():
    """Two jobs per merge fill the lane's two relay slots, and the next merge's close waits for one to re-register."""
    on_the_lane = sorted(
        path.name
        for path in WORKFLOWS.glob("*.yml")
        for spec in yaml.safe_load(path.read_text())["jobs"].values()
        if "merge-event" in str(spec["runs-on"])
    )
    assert on_the_lane == ["main-follow-on-close.yml"]


def test_merged_pull_request_dispatch_runs_on_the_general_lane():
    assert job("dispatch-merged.yml", "dispatch")["runs-on"] == ["self-hosted", "ai-vm-1"]


def test_merged_pull_request_dispatch_skips_unmerged_and_fork_pull_requests():
    condition = job("dispatch-merged.yml", "dispatch")["if"]
    assert "merged == true" in condition
    assert "head.repo.full_name == github.repository" in condition


def test_merged_pull_request_dispatch_sends_only_after_the_tree_check_passes():
    steps = job("dispatch-merged.yml", "dispatch")["steps"]
    send = next(step for step in steps if step["name"] == "Dispatch the merged SHA")
    assert steps.index(send) > next(i for i, step in enumerate(steps) if step.get("id") == "tested")
    assert send["if"] == "steps.tested.outputs.tested == 'true'"


def run_step(step: dict, tmp_path, env: dict[str, str], *, uv_exit: int = 0) -> int:
    """Run a workflow step's shell with the given environment and a stub `uv` that exits `uv_exit`; return its status."""
    stub = tmp_path / "uv"
    stub.write_text(f"#!/usr/bin/env bash\nexit {uv_exit}\n")
    stub.chmod(0o755)
    shell = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        check=False,
    )
    return shell.returncode


def test_the_shard_count_matches_the_shard_matrix():
    shard = job("ci.yml", "python-shard")
    assert shard["env"]["SHARD_COUNT"] == len(shard["strategy"]["matrix"]["shard"])
    assert shard["env"]["SHARD_INDEX"] == "${{ matrix.shard }}"


@pytest.mark.parametrize(("result", "status"), [("success", 0), ("failure", 1), ("cancelled", 1), ("skipped", 1)])
def test_the_python_check_passes_only_when_every_shard_passed(tmp_path, result, status):
    """The ruleset requires `python`: a red, cancelled or skipped shard must not leave it green or missing."""
    aggregate = job("ci.yml", "python")
    assert aggregate["needs"] == "python-shard"
    # A skipped aggregate reads as a missing required check; a push carries none, so it skips there with the shards.
    assert aggregate["if"] == "always() && github.event_name != 'push'"
    step = aggregate["steps"][0]
    assert step["env"] == {"SHARDS": "${{ needs.python-shard.result }}"}
    assert run_step(step, tmp_path, {"SHARDS": result}) == status


def pytest_step() -> dict:
    return next(
        step for step in job("ci.yml", "python-shard")["steps"] if "pytest $PYTEST_TARGETS" in step.get("run", "")
    )


@pytest.mark.parametrize(
    ("targets", "pytest_exit", "status"),
    [
        ("", 0, 0),
        ("", 1, 1),
        ("", 5, 1),  # a full run that collects nothing is broken
        ("ci/test_a.py", 0, 0),
        ("ci/test_a.py", 1, 1),
        ("ci/test_a.py", 5, 0),  # this shard drew none of the selected files
    ],
)
def test_a_shard_with_no_selected_files_passes_but_a_failing_or_empty_full_run_does_not(
    tmp_path, targets, pytest_exit, status
):
    assert run_step(pytest_step(), tmp_path, {"PYTEST_TARGETS": targets}, uv_exit=pytest_exit) == status


#: The ruleset's required checks (trantor's infrastructure/github/starpulse.tf), by the workflow that reports each.
REQUIRED_CHECKS = [
    ("ci.yml", "python"),
    ("ci.yml", "web"),
    ("ci.yml", "api-types"),
    ("ci.yml", "tier-policy"),
    ("ci.yml", "static-checks"),
    ("ci.yml", "trantor-contract"),
    ("release.yml", "build"),
]


@pytest.mark.parametrize(("workflow", "name"), REQUIRED_CHECKS)
def test_every_required_check_reports_on_a_merge_queue_candidate(workflow, name):
    """The merge queue waits for each required check on the candidate; one that never reports fails the entry."""
    document = yaml.safe_load((WORKFLOWS / workflow).read_text())
    assert document[True]["merge_group"] == {"types": ["checks_requested"]}
    assert "merge_group" not in job(workflow, name).get("if", "")


@pytest.mark.parametrize(
    ("workflow", "name"),
    [("ci.yml", "dispatch"), ("release.yml", "soak"), ("release.yml", "github-release"), ("release.yml", "pypi")],
)
def test_a_merge_queue_candidate_dispatches_soaks_and_publishes_nothing(workflow, name):
    """The candidate is not on main yet: dispatching it pins a SHA trantor cannot fetch, and a soak holds Tower for hours."""
    condition = job(workflow, name)["if"]
    assert "github.event_name == 'push'" in condition or "github.event_name != 'merge_group'" in condition


def run_tree_check(tmp_path, *, parent, base, pr_runs, queue_runs):
    """Run dispatch-merged.yml's tree check against a stub `gh` and return what it wrote to GITHUB_OUTPUT."""
    step = next(s for s in job("dispatch-merged.yml", "dispatch")["steps"] if s.get("id") == "tested")
    stub = tmp_path / "gh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'case "$2" in\n'
        f'  */commits/*) echo "{parent}" ;;\n'
        f'  *event=pull_request*) echo "{pr_runs}" ;;\n'
        f'  *event=merge_group*) echo "{queue_runs}" ;;\n'
        '  *) echo "unexpected gh call: $*" >&2; exit 1 ;;\n'
        "esac\n"
    )
    stub.chmod(0o755)
    output = tmp_path / "output"
    output.write_text("")
    env = {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "GITHUB_OUTPUT": str(output),
        "REPOSITORY": "trantor-org/starpulse",
        "MERGE_SHA": "m" * 40,
        "BASE_SHA": base,
        "HEAD_SHA": "h" * 40,
    }
    subprocess.run(["bash", "-e", "-c", step["run"]], env=env, check=True, capture_output=True, text=True)
    return output.read_text()


def test_merged_pull_request_dispatch_sends_a_queue_merge_its_green_candidate_tested(tmp_path):
    """A queue merge's base is stale, but the green merge_group run on the merge commit tested exactly that tree."""
    assert run_tree_check(tmp_path, parent="p" * 40, base="b" * 40, pr_runs=0, queue_runs=1) == "tested=true\n"


def test_merged_pull_request_dispatch_leaves_a_stale_base_with_no_green_candidate_to_the_push_run(tmp_path):
    assert run_tree_check(tmp_path, parent="p" * 40, base="b" * 40, pr_runs=1, queue_runs=0) == ""


def test_merged_pull_request_dispatch_still_sends_a_current_base_its_pull_request_run_tested(tmp_path):
    assert run_tree_check(tmp_path, parent="b" * 40, base="b" * 40, pr_runs=1, queue_runs=0) == "tested=true\n"
