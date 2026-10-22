"""Where each workflow job runs: the nightly suite and the release soak on the ai-vm-1 fleet, tag publishing on hosted runners."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
AI_VM_1_LANE = ["self-hosted", "ai-vm-1"]
HOSTED = "ubuntu-latest"
#: The required checks a pull request and a merge candidate get from ci.yml.
REQUIRED_CHECKS = ["python", "web", "static-checks", "build"]
APP_CHECKS = REQUIRED_CHECKS
CI_TEST_JOBS = ["select", "python-shard", "python", "build", "web", "static-checks", "fresh-serve", "latency-gate"]


def job(workflow: str, name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][name]


@pytest.mark.parametrize(
    ("workflow", "name"),
    [
        ("ui-preview.yml", "render"),
        ("ui-preview.yml", "leak-scan"),
    ],
)
def test_pull_request_job_runs_on_the_ai_vm_1_fleet(workflow, name):
    assert job(workflow, name)["runs-on"] == AI_VM_1_LANE


@pytest.mark.parametrize("name", CI_TEST_JOBS)
def test_ci_test_job_runs_on_the_ai_vm_1_fleet(name):
    assert job("ci.yml", name)["runs-on"] == AI_VM_1_LANE


def test_ci_runs_on_a_pull_request_a_merge_candidate_the_nightly_a_dispatch_and_a_push():
    """This workflow defines the required checks: a pull request and a merge-queue candidate run them on the changed files."""
    document = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    assert set(document[True]) == {"push", "pull_request", "merge_group", "schedule", "workflow_dispatch"}


@pytest.mark.parametrize("name", REQUIRED_CHECKS)
def test_every_required_check_is_a_ci_job(name):
    """The job id is the check's context; `build` is the release build without its publishing."""
    assert name in yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]


@pytest.mark.parametrize("name", ["coverage-map", "python-ft", "macos-fresh-serve", "clean-machine-ingest"])
def test_a_nightly_only_job_skips_a_pull_request(name):
    """A pull request's partial selection would publish a partial coverage map, and the others cost a whole-suite run."""
    condition = job("ci.yml", name)["if"]
    assert "'schedule'" in condition
    assert "pull_request" not in condition


def test_release_build_runs_hosted_for_a_push_and_on_the_ai_vm_1_fleet_otherwise():
    """A tag and a merge to main both publish what the build makes, so both build on a clean hosted runner."""
    runs_on = job("release.yml", "build")["runs-on"]
    match = re.fullmatch(
        r"\$\{\{ github\.event_name == 'push' && '([^']+)' \|\| fromJSON\('([^']+)'\) \}\}", runs_on
    )
    assert match, runs_on
    push_runner, other_runner = match.groups()
    assert push_runner == HOSTED
    assert json.loads(other_runner) == AI_VM_1_LANE


@pytest.mark.parametrize("name", ["github-release", "pypi"])
def test_publishing_job_runs_on_a_hosted_runner(name):
    assert job("release.yml", name)["runs-on"] == HOSTED


@pytest.mark.parametrize(
    ("workflow", "name"),
    [
        ("ci.yml", "web"),
        ("ci.yml", "static-checks"),
        ("release.yml", "build"),
        ("release.yml", "soak"),
        ("ui-preview.yml", "render"),
    ],
)
def test_node_is_installed_before_pnpm(workflow, name):
    """`pnpm/action-setup` installs pnpm with the runner's `npm`, which fails under the system Node of a self-hosted runner."""
    uses = [step["uses"].split("@")[0] for step in job(workflow, name)["steps"] if "uses" in step]
    assert uses.index("actions/setup-node") < uses.index("pnpm/action-setup")


def needs(workflow: str, name: str) -> list[str]:
    declared = job(workflow, name).get("needs", [])
    return [declared] if isinstance(declared, str) else declared


def test_release_soak_runs_on_the_ai_vm_1_fleet_after_the_build_and_does_not_gate_publishing():
    """The soak runs after a green build; a red soak does not hold the GitHub Release or PyPI."""
    assert job("release.yml", "soak")["runs-on"] == AI_VM_1_LANE
    assert "build" in needs("release.yml", "soak")
    assert "build" in needs("release.yml", "github-release")
    assert "soak" not in needs("release.yml", "github-release")
    assert "soak" not in needs("release.yml", "pypi")


def test_a_failed_or_cancelled_release_soak_files_a_github_issue_naming_the_tag_and_run():
    """Publishing no longer waits; a red or cancelled soak still records the tag and the run as an issue."""
    alert = job("release.yml", "soak-alert")
    step = next(s for s in alert["steps"] if "gh issue create" in s.get("run", ""))
    env = step.get("env", {})

    assert needs("release.yml", "soak-alert") == ["soak"]
    assert "needs.soak.result" in alert["if"]
    assert "failure" in alert["if"] and "cancelled" in alert["if"]
    assert env.get("TAG") == "${{ github.ref_name }}"
    assert "github.run_id" in env.get("RUN_URL", "")
    assert "${TAG}" in step["run"] and "${RUN_URL}" in step["run"]


def test_release_soak_runs_for_a_tag_or_a_dispatch_and_publishing_only_for_a_push():
    """A merge to main never takes a runner for hours, and a dispatch on a tag's ref publishes nothing."""
    assert job("release.yml", "soak")["if"] == "github.ref_type == 'tag' || github.event_name == 'workflow_dispatch'"
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
    """A 4 hour hold is not restarted by the next run: one holds a runner, the next waits."""
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


def test_no_job_or_check_reaches_a_checkout_of_another_repository():
    """The package is tested on its own tree alone: no job fetches the workspace that consumes it."""
    jobs = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]
    for name, body in jobs.items():
        for step in body.get("steps", []):
            assert "repository" not in step.get("with", {}), name


#: Every ci.yml job but the macOS smoke: the jobs that test a tree.
TEST_JOBS = [
    "select",
    "python-shard",
    "coverage-map",
    "python-ft",
    "python",
    "build",
    "web",
    "static-checks",
    "fresh-serve",
    "latency-gate",
]


@pytest.mark.parametrize("name", TEST_JOBS)
def test_a_push_to_main_runs_no_test_job(name):
    """Main moves only through the merge queue, which already tested the pushed commit (its candidate)."""
    condition = job("ci.yml", name)["if"]
    assert "github.event_name != 'push'" in condition or "github.event_name == 'schedule'" in condition


def test_every_ci_job_but_the_macos_smoke_is_a_test_job():
    jobs = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]
    assert sorted(jobs) == sorted([*TEST_JOBS, "macos-fresh-serve", "clean-machine-ingest"])


def test_the_coverage_map_is_published_only_by_a_green_nightly_and_is_no_required_check():
    """A red shard's coverage data would leave tests out of the map the select step reads."""
    assert "python-shard" in needs("ci.yml", "coverage-map")
    assert "needs.python-shard.result == 'success'" in job("ci.yml", "coverage-map")["if"]
    assert "coverage-map" not in needs("ci.yml", "python")
    assert "coverage-map" not in APP_CHECKS


def test_the_free_threaded_suite_runs_beside_the_shards_and_is_no_required_check():
    """The live server runs on 3.14t, so a change that breaks that build must show in the nightly run. The job is
    not a required check: `python` neither waits for it nor counts it."""
    ft = job("ci.yml", "python-ft")
    assert ft["runs-on"] == AI_VM_1_LANE
    assert "select" in needs("ci.yml", "python-ft")
    assert "python-ft" not in needs("ci.yml", "python")
    assert "python-ft" not in APP_CHECKS


def test_the_free_threaded_suite_fails_when_the_gil_comes_back():
    """A dependency that re-enables the GIL on import
    would leave the job green on the build it does not test, so the job checks the interpreter after the imports."""
    runs = "\n".join(step["run"] for step in job("ci.yml", "python-ft")["steps"] if "run" in step)
    assert "uv sync --locked --python 3.14t" in runs
    assert "sys._is_gil_enabled()" in runs
    assert "PYTEST_TARGETS" in runs  # the same selected tests as the shards


def test_the_free_threaded_environment_lives_outside_the_checkout_and_is_set_in_a_step():
    """A runner's workspace outlives the job, so a 3.14t .venv in it would move the next job onto the free-threaded
    build. GitHub rejects the whole workflow when a job-level env reads the runner context, which it does not offer."""
    ft = job("ci.yml", "python-ft")
    assert "runner" not in str(ft.get("env", {}))
    runs = "\n".join(step["run"] for step in ft["steps"] if "run" in step)
    assert 'UV_PROJECT_ENVIRONMENT=$RUNNER_TEMP/ft-venv" >> "$GITHUB_ENV"' in runs


STATIC_SCRIPT = WORKFLOWS.parents[1] / "ci/static_checks.sh"


def test_the_four_short_jobs_are_gone_and_static_checks_runs_every_check_they_ran():
    """public-names and api-types share one job so a run starts fewer jobs."""
    jobs = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]
    assert not {"ic", "public-names", "api-types", "tier-policy"} & jobs.keys()
    script = STATIC_SCRIPT.read_text()
    runs = "\n".join(step["run"] for step in job("ci.yml", "static-checks")["steps"] if "run" in step)
    assert "ci/static_checks.sh" in runs
    for command in (
        "ci/public_names.py",
        "python -m starpulse.contracts.api",  # api-types: regenerate both outputs, fail on a diff
        "pnpm --dir starpulse/web run gen:types",
        "git diff --exit-code -- starpulse/api.schema.json starpulse/web/src/api/types.gen.ts",
    ):
        assert command in script, command


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
        ("ci/public_names.py", "public-names"),
        ("gen:types", "api-types"),
    ],
)
def test_static_checks_fails_naming_the_failed_check_and_still_runs_the_others(tmp_path, fail_on, name):
    result = run_static_checks(tmp_path, fail_on=fail_on)
    assert result.returncode == 1
    assert re.findall(r"static check failed: (\S+)", result.stdout) == [name]
    calls = (tmp_path / "calls").read_text()
    assert all(command in calls for command in ("ci/public_names.py", "gen:types"))


def test_static_checks_runs_its_checks_concurrently(tmp_path):
    """Run in sequence, the first check's last call would come before the second's first; started together, it follows."""
    result = run_static_checks(tmp_path, delay=0.3)
    calls = (tmp_path / "calls").read_text().splitlines()
    assert result.returncode == 0
    first_of_second = next(i for i, call in enumerate(calls) if "ci/public_names.py" in call)
    last_of_first = max(i for i, call in enumerate(calls) if call.startswith("git diff"))
    assert first_of_second < last_of_first


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


def test_the_shard_count_is_the_size_of_the_matrix_the_selection_made():
    shard = job("ci.yml", "python-shard")
    assert shard["env"]["SHARD_COUNT"] == "${{ strategy.job-total }}"
    assert shard["env"]["SHARD_INDEX"] == "${{ matrix.shard }}"


def test_the_python_check_waits_for_the_selection_and_the_shards_and_runs_behind_a_red_one():
    aggregate = job("ci.yml", "python")
    assert aggregate["needs"] == ["select", "python-shard"]
    # A skipped aggregate reads as a missing required check; a push carries none, so it skips there with the shards.
    assert aggregate["if"] == "always() && github.event_name != 'push'"
    assert aggregate["steps"][0]["env"] == {
        "SELECT": "${{ needs.select.result }}",
        "SHARDS": "${{ needs.python-shard.result }}",
        "LAUNCHED": "${{ needs.select.outputs.PYTEST_SHARDS }}",
    }


@pytest.mark.parametrize(
    ("select_result", "shards", "launched", "status"),
    [
        ("success", "success", "[1, 2, 3]", 0),
        ("success", "skipped", "[]", 0),  # no test selected: no shard launched, none failed
        ("success", "failure", "[1, 2, 3]", 1),
        ("success", "cancelled", "[1, 2, 3]", 1),
        ("success", "skipped", "[1, 2, 3]", 1),  # shards were wanted and never ran
        ("failure", "skipped", "", 1),  # a failed selection or lint skips the shards and leaves its outputs empty
        ("cancelled", "skipped", "[]", 1),
        ("failure", "success", "[1]", 1),
    ],
)
def test_the_python_check_passes_when_every_launched_shard_passed_or_none_was_needed(
    tmp_path, select_result, shards, launched, status
):
    """The ruleset requires `python`: a red, cancelled or never-run shard must not leave it green or missing."""
    step = job("ci.yml", "python")["steps"][0]
    env = {"SELECT": select_result, "SHARDS": shards, "LAUNCHED": launched}
    assert run_step(step, tmp_path, env) == status


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


def test_release_runs_only_the_push_and_dispatch_events():
    """A pull request and a merge-queue candidate get the required `build` from ci.yml, not from this workflow."""
    document = yaml.safe_load((WORKFLOWS / "release.yml").read_text())
    assert set(document[True]) == {"push", "workflow_dispatch"}


def test_a_merge_to_main_that_changes_the_wheel_triggers_a_release_run():
    """The wheel is the `starpulse` package without its tests, plus the project file that names its dependencies and version."""
    push = yaml.safe_load((WORKFLOWS / "release.yml").read_text())[True]["push"]
    assert push["tags"] == ["v*"]
    assert push["branches"] == ["main"]
    assert push["paths"] == ["starpulse/**", "!starpulse/tests/**", "pyproject.toml"]


def test_a_merge_to_main_publishes_a_beta_version_that_only_the_runner_holds():
    """`cz bump` rewrites the runner's checkout only (no commit, no tag), so main never carries a beta and a run cannot loop."""
    build = job("release.yml", "build")
    step = next(s for s in build["steps"] if "cz bump" in s.get("run", ""))
    command = step["run"]

    assert step["if"] == "github.ref_type == 'branch' && github.event_name == 'push'"
    assert "--prerelease beta" in command and "--files-only" in command
    assert "--increment PATCH" in command
    assert '--prerelease-offset "$GITHUB_RUN_NUMBER"' in command
    assert build["outputs"]["tag"] == "${{ steps.tag.outputs.tag }}"
    tag_step = next(s for s in build["steps"] if s.get("id") == "tag")
    assert 'echo "tag=v$(uv version --short)" >> "$GITHUB_OUTPUT"' in tag_step["run"]


def test_a_beta_release_is_a_prerelease_cut_at_the_merged_commit_and_a_tag_release_verifies_its_tag():
    release = job("release.yml", "github-release")
    step = next(s for s in release["steps"] if "gh release create" in s.get("run", ""))

    assert step["env"]["TAG"] == "${{ needs.build.outputs.tag }}"
    assert 'flags=(--verify-tag)' in step["run"]
    assert 'flags=(--target "$GITHUB_SHA" --prerelease)' in step["run"]
    assert '"$TAG"' in step["run"] and '"${flags[@]}"' in step["run"]


def test_starpulse_names_its_commitizen_version_source_and_treats_a_breaking_change_as_a_minor_before_1_0():
    commitizen = tomllib.loads((WORKFLOWS.parents[1] / "pyproject.toml").read_text())["tool"]["commitizen"]
    assert commitizen["version_provider"] == "uv"
    assert commitizen["tag_format"] == "v$version"
    assert commitizen["major_version_zero"] is True


def test_ci_runs_the_fresh_install_smoke_on_a_hosted_macos_runner():
    """The Linux smoke is the fresh-serve job; macOS has no fleet runner, so a hosted one proves the supervisor, resident-size reader and socket handoff there."""
    smoke = job("ci.yml", "macos-fresh-serve")
    assert smoke["runs-on"] == "macos-latest"
    assert any("ci/fresh_serve.py" in step.get("run", "") for step in smoke["steps"])


def test_ci_proves_the_ingest_on_a_hosted_runner_with_no_redis():
    """The ai-vm-1 fleet sits beside a Redis; a hosted runner has none, so only it can show the ingest needs none."""
    proof = job("ci.yml", "clean-machine-ingest")
    assert proof["runs-on"] == "ubuntu-latest"
    assert "github.event_name == 'schedule'" in proof["if"]
    assert any("ci/clean_machine.py" in step.get("run", "") for step in proof["steps"])
