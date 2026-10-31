"""Where each workflow job runs: every job on a hosted runner, none on the ai-vm-1 lane, whose work is Dagu DAGs."""

from __future__ import annotations

import re
import subprocess
import time
import tomllib
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
AI_VM_1_LANE = ["self-hosted", "ai-vm-1"]
HOSTED = "ubuntu-latest"
#: The required checks' jobs, which moved to the sp-ci Dagu DAG and left ci.yml.
MOVED_CHECKS = ["python", "web", "static-checks", "build"]


def job(workflow: str, name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][name]


def test_no_workflow_job_runs_on_the_ai_vm_1_lane():
    """The lane's work is Dagu DAGs: the nightly suite, the soak, the UI preview and the repository checks."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, body in yaml.safe_load(path.read_text())["jobs"].items():
            assert body["runs-on"] != AI_VM_1_LANE, f"{path.name}/{name}"


def test_ci_runs_on_the_nightly_and_a_dispatch_only():
    """A pull request, a merge-queue candidate and a push get their checks from the sp-ci Dagu DAG, not from Actions."""
    document = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    assert set(document[True]) == {"schedule", "workflow_dispatch"}


def test_ci_keeps_only_the_jobs_a_hosted_runner_must_run():
    assert sorted(yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]) == [
        "clean-machine-ingest",
        "macos-fresh-serve",
    ]


@pytest.mark.parametrize("name", MOVED_CHECKS)
def test_a_required_check_is_no_ci_job(name):
    assert name not in yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]


@pytest.mark.parametrize("name", ["macos-fresh-serve", "clean-machine-ingest"])
def test_a_nightly_only_job_skips_a_pull_request(name):
    """Each costs a whole-suite run or a hosted macOS minute."""
    condition = job("ci.yml", name)["if"]
    assert "'schedule'" in condition
    assert "pull_request" not in condition


@pytest.mark.parametrize("name", ["build", "github-release", "pypi"])
def test_release_job_runs_on_a_hosted_runner(name):
    """What the build makes is published, so it builds on a clean runner."""
    assert job("release.yml", name)["runs-on"] == HOSTED


@pytest.mark.parametrize(
    ("workflow", "name"),
    [
        ("release.yml", "build"),
    ],
)
def test_node_is_installed_before_pnpm(workflow, name):
    """`pnpm/action-setup` installs pnpm with the runner's `npm`, which fails under the system Node of a self-hosted runner."""
    uses = [step["uses"].split("@")[0] for step in job(workflow, name)["steps"] if "uses" in step]
    assert uses.index("actions/setup-node") < uses.index("pnpm/action-setup")


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


STATIC_SCRIPT = WORKFLOWS.parents[1] / "ci/static_checks.sh"
RUN = WORKFLOWS.parents[1] / "ci/run.sh"


def test_static_checks_script_runs_every_check_the_short_jobs_ran():
    """public-names, api-types and wire-pb2 share one script, which the sp-ci DAG reaches through ci/run.sh."""
    script = STATIC_SCRIPT.read_text()
    assert "ci/static_checks.sh" in RUN.read_text()
    for command in (
        "ci/public_names.py",
        "python -m starpulse.contracts.api",  # api-types: regenerate both outputs, fail on a diff
        "pnpm --dir starpulse/web run gen:types",
        "git diff --exit-code -- starpulse/schemas/api.schema.json starpulse/web/src/api/types.gen.ts",
        "python -m grpc_tools.protoc",  # wire-pb2: regenerate the protobuf modules, fail on a diff
        "git diff --exit-code -- starpulse/runs/wire",
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
        ("grpc_tools.protoc", "wire-pb2"),
    ],
)
def test_static_checks_fails_naming_the_failed_check_and_still_runs_the_others(tmp_path, fail_on, name):
    result = run_static_checks(tmp_path, fail_on=fail_on)
    assert result.returncode == 1
    assert re.findall(r"static check failed: (\S+)", result.stdout) == [name]
    calls = (tmp_path / "calls").read_text()
    assert all(command in calls for command in ("ci/public_names.py", "gen:types", "grpc_tools.protoc"))


def test_static_checks_runs_its_checks_concurrently(tmp_path):
    """Run in sequence, the first check's last call would come before the second's first; started together, it follows."""
    result = run_static_checks(tmp_path, delay=0.3)
    calls = (tmp_path / "calls").read_text().splitlines()
    assert result.returncode == 0
    first_of_second = next(i for i, call in enumerate(calls) if "ci/public_names.py" in call)
    last_of_first = max(i for i, call in enumerate(calls) if call.startswith("git diff"))
    assert first_of_second < last_of_first


def run_ci(command: str, tmp_path, env: dict[str, str], *, pytest_exit: int = 0) -> int:
    """Run `ci/run.sh <command>` with the given environment and a stub `uv` whose pytest exits `pytest_exit`; return its status."""
    stub = tmp_path / "uv"
    stub.write_text(
        f'#!/usr/bin/env bash\n[[ "$*" == *pytest* ]] && exit {pytest_exit}\n[[ "$*" == *xdist_workers* ]] && echo 2\nexit 0\n'
    )
    stub.chmod(0o755)
    shell = subprocess.run(
        [str(RUN), command],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "PYTEST_LOG": str(tmp_path / "pytest.log"), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    return shell.returncode


@pytest.mark.parametrize(
    ("targets", "pytest_exit", "status"),
    [
        ("", 0, 0),
        ("", 1, 1),
        ("", 5, 1),  # a full run that collects nothing is broken
        ("ci/test_a.py", 0, 0),
        ("ci/test_a.py", 1, 1),
        ("ci/test_a.py", 5, 0),  # the selected files collect no test
    ],
)
def test_a_targeted_run_collecting_no_test_passes_but_a_failing_or_empty_full_run_does_not(
    tmp_path, targets, pytest_exit, status
):
    assert run_ci("python-tests", tmp_path, {"PYTEST_TARGETS": targets}, pytest_exit=pytest_exit) == status


def test_release_runs_only_the_push_and_dispatch_events():
    """A pull request and a merge-queue candidate get no check from this workflow."""
    document = yaml.safe_load((WORKFLOWS / "release.yml").read_text())
    assert set(document[True]) == {"push", "workflow_dispatch"}


def test_a_merge_to_main_that_changes_the_wheel_triggers_a_release_run():
    """The wheel is the `starpulse` package (the tests live beside it, not in it), plus the project file that names its dependencies and version."""
    push = yaml.safe_load((WORKFLOWS / "release.yml").read_text())[True]["push"]
    assert push["tags"] == ["v*"]
    assert push["branches"] == ["main"]
    assert push["paths"] == ["starpulse/**", "pyproject.toml"]


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
    assert "flags=(--verify-tag)" in step["run"]
    assert 'flags=(--target "$GITHUB_SHA" --prerelease)' in step["run"]
    assert '"$TAG"' in step["run"] and '"${flags[@]}"' in step["run"]


def test_starpulse_names_its_commitizen_version_source_and_treats_a_breaking_change_as_a_minor_before_1_0():
    commitizen = tomllib.loads((WORKFLOWS.parents[1] / "pyproject.toml").read_text())["tool"]["commitizen"]
    assert commitizen["version_provider"] == "uv"
    assert commitizen["tag_format"] == "v$version"
    assert commitizen["major_version_zero"] is True


def test_ci_runs_the_fresh_install_smoke_on_a_hosted_macos_runner():
    """The Linux smoke is the nightly DAG's fresh-serve job; Dagu has no macOS worker, so a hosted runner proves the supervisor, resident-size reader and socket handoff there."""
    smoke = job("ci.yml", "macos-fresh-serve")
    assert smoke["runs-on"] == "macos-latest"
    assert any("ci/fresh_serve.py" in step.get("run", "") for step in smoke["steps"])


def test_ci_proves_the_ingest_on_a_hosted_runner_with_no_redis():
    """The ai-vm-1 workers sit beside a Redis; a hosted runner has none, so only it can show the ingest needs none."""
    proof = job("ci.yml", "clean-machine-ingest")
    assert proof["runs-on"] == "ubuntu-latest"
    assert "github.event_name == 'schedule'" in proof["if"]
    assert any("ci/clean_machine.py" in step.get("run", "") for step in proof["steps"])


def test_the_build_job_builds_in_a_scratch_checkout_so_it_never_empties_the_clones_static_under_the_running_python_step():
    """vite empties starpulse/static; the python step of the same sp-ci clone holds a stub there while it runs."""
    body = RUN.read_text().split("cmd_build() {")[1].split("\n}\n")[0]
    assert "git worktree add --detach" in body
    assert body.index("git worktree add") < body.index("pnpm --dir starpulse/web run build")


def run_select(tmp_path, *, delay: float) -> subprocess.CompletedProcess:
    """`ci/run.sh select` over an empty diff, with a `uv` that prints one line per script after `delay` seconds."""
    stub = tmp_path / "uv"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"sleep {delay}\n"
        'case "$*" in *select_tests*) echo PYTEST_TARGETS=ci/a.py;; *reach*) echo web=true;; esac\n'
    )
    stub.chmod(0o755)
    return subprocess.run(
        [str(RUN), "select"],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "BASE": "HEAD"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_select_prints_the_selection_then_the_reach_lines_while_running_both_at_once(tmp_path):
    started = time.monotonic()
    result = run_select(tmp_path, delay=1.0)
    elapsed = time.monotonic() - started
    assert result.stdout == "PYTEST_TARGETS=ci/a.py\nweb=true\n"
    assert elapsed < 1.8, "the two scripts ran one after the other"
