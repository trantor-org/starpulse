"""starpulse/web/scripts/check.sh -- which vitest tests and which build the gate runs for a change."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "starpulse" / "web" / "scripts" / "check.sh"


def _plan(*args: str) -> list[str]:
    done = subprocess.run(["sh", str(SCRIPT), "--plan", *args], capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


def test_the_nightly_run_runs_every_test_and_both_builds() -> None:
    assert _plan() == ["test: all", "build: pnpm run build"]


def test_a_source_change_runs_the_tests_importing_it_and_one_build() -> None:
    plan = _plan("--changed", "starpulse/web/src/util.ts", "starpulse/x.py")

    assert plan == ["test: related src/util.ts", "build: pnpm exec vite build"]


def test_a_config_or_lockfile_change_runs_every_test() -> None:
    for file in ("package.json", "pnpm-lock.yaml", "vite.config.ts", "scripts/in-tests-slice.sh"):
        assert _plan("--changed", "starpulse/web/src/a.ts", f"starpulse/web/{file}")[0] == "test: all"


def test_a_change_outside_the_web_app_runs_no_test() -> None:
    assert _plan("--changed", "starpulse/x.py")[0] == "test: none"
