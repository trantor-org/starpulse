#!/usr/bin/env bash
# One entry point per required CI context: `ci/run.sh python|web|static-checks|build`. Each runs from any directory,
# installs what it reads and exits 0 only when its context is green, so ci.yml and any other runner share one definition.
# `select` and `python-tests` are the two pieces `python` is built from; ci.yml's `select` and `python-tests` jobs and sp-ci's
# `select` and `python` steps run them apart.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Chooses the tests and the checks a change reaches, as `KEY=value` lines on stdout (the rest goes to stderr). Without
# BASE it selects the whole suite; with it, by the files changed since BASE (ci/select_tests.py, ci/reach.py). Both import
# only the standard library, so it syncs nothing: `--no-sync` runs them in whatever environment the project resolves to.
cmd_select() {
  if [ -z "${BASE:-}" ]; then
    uv run --no-sync python ci/select_tests.py --full
    printf 'web=true\nstatic=true\n'
    return
  fi
  local changed
  changed=$(mktemp)
  git diff --name-only --no-renames "$BASE" HEAD >"$changed"
  uv run --no-sync python ci/select_tests.py --base "$BASE" <"$changed"
  uv run --no-sync python ci/reach.py <"$changed"
  rm -f "$changed"
}

# The suite in one pytest session over PYTEST_TARGETS (empty is the whole suite): work-stealing xdist workers
# (`--dist worksteal`) sized to the `tests.slice` budget on the build host (ci/xdist_workers.py --slice), or to the
# runner's memory limit anywhere else. PYTEST_WORKERS, when the caller sets it, is that count instead: sp-ci's share of
# tests.slice among every CI run (ci-pytest-workers). `-rA` ends the log with one PASSED/FAILED line per test, so a log
# names each test's outcome. TEST_COST_REPORT set is the nightly or a dispatch: it adds the nightly-marked tests
# and, as `1`, the coverage data that ci/coverage_map.py combines.
cmd_python_tests() {
  uv sync --locked
  local sizing=""
  if [ -d /sys/fs/cgroup/tests.slice ]; then
    sizing=--slice
  fi
  # shellcheck disable=SC2086 # sizing is empty or one flag
  local workers="${PYTEST_WORKERS:-$(uv run --no-sync python ci/xdist_workers.py $sizing)}"
  local addopts="-n $workers --dist worksteal -rA"
  if [ -n "${TEST_COST_REPORT:-}" ]; then
    addopts+=" -m 'not e2e'"
  fi
  if [ "${TEST_COST_REPORT:-}" = 1 ]; then
    addopts+=" --cov --cov-context=test --cov-report="
  fi
  export PYTEST_ADDOPTS=$addopts
  # Pytest exits 5 when it collects no test, which is a pass only while targets were selected.
  # The full log is kept: an xdist worker crash (INTERNALERROR) prints its traceback only into this output.
  local status=0
  # shellcheck disable=SC2086 # PYTEST_TARGETS is a list of paths
  uv run --no-sync pytest ${PYTEST_TARGETS:-} 2>&1 | tee "${PYTEST_LOG:-pytest.log}" || status=$?
  [ "$status" -eq 0 ] || { [ "$status" -eq 5 ] && [ -n "${PYTEST_TARGETS:-}" ]; }
}

# The whole context on this machine: select, then every selected test in one run.
cmd_python() {
  local selected targets python
  selected=$(cmd_select)
  targets=$(sed -n 's/^PYTEST_TARGETS=//p' <<<"$selected")
  python=$(sed -n 's/^python=//p' <<<"$selected")
  if [ "$python" = false ]; then
    echo "no test selected"
    return
  fi
  PYTEST_TARGETS=$targets cmd_python_tests
}

cmd_web() {
  pnpm --dir starpulse/web install --frozen-lockfile
  pnpm --dir starpulse/web run check
}

cmd_static_checks() {
  bash ci/static_checks.sh
}

# The release build without publishing (release.yml's `build`): the page, then the wheel that must ship it. It builds in a
# scratch checkout: vite empties starpulse/static, which the python step of the same sp-ci clone reads while it runs.
cmd_build() {
  local work dist
  work=$(mktemp -d)
  dist=$(mktemp -d)
  trap 'git worktree remove --force "$work"; rm -rf "$dist"' RETURN
  git worktree add --detach "$work" HEAD >&2
  (
    cd "$work"
    pnpm --dir starpulse/web install --frozen-lockfile
    pnpm --dir starpulse/web run build
    uv build --out-dir "$dist"
    # grep -c reads the whole listing: under pipefail, grep -q closing the pipe early would fail the step.
    [ "$(uv run python -m zipfile -l "$dist"/*.whl | grep -c 'starpulse/static/index.html')" -gt 0 ]
  )
}

case "${1:-}" in
  select | python-tests | python | web | static-checks | build)
    "cmd_${1//-/_}"
    ;;
  *)
    echo "usage: ci/run.sh python|web|static-checks|build (or select|python-tests)" >&2
    exit 2
    ;;
esac
