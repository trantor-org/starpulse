#!/usr/bin/env bash
# One entry point per required CI context: `ci/run.sh python|web|static-checks|build`. Each runs from any directory,
# installs what it reads and exits 0 only when its context is green, so ci.yml and any other runner share one definition.
# `select` and `python-shard` are the two pieces `python` is built from; ci.yml's `select` and `python-shard` jobs run them
# apart to fan the suite out over runners.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Chooses the tests and the checks a change reaches, as `KEY=value` lines on stdout (the rest goes to stderr). Without
# BASE it selects the whole suite; with it, by the files changed since BASE (ci/select_tests.py, ci/reach.py).
cmd_select() {
  uv sync --locked >&2
  uv run --no-sync lint-imports >&2
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

# One shard of the suite: SHARD_INDEX of SHARD_COUNT (ci/shard.py; both unset runs every test) over PYTEST_TARGETS (empty is
# the whole suite). TEST_COST_REPORT set is the nightly or a dispatch: it adds the nightly-marked tests and, as `1`, the
# coverage data that ci/coverage_map.py combines.
cmd_python_shard() {
  uv sync --locked
  local addopts
  addopts="-n $(uv run --no-sync python ci/xdist_workers.py) --dist worksteal"
  if [ -n "${TEST_COST_REPORT:-}" ]; then
    addopts+=" -m 'not e2e'"
  fi
  if [ "${TEST_COST_REPORT:-}" = 1 ]; then
    addopts+=" --cov --cov-context=test --cov-report="
  fi
  export PYTEST_ADDOPTS=$addopts
  # A selected run can leave a shard no test file: pytest exits 5 for it, which is a pass only while targets were selected.
  # The full log is kept: an xdist worker crash (INTERNALERROR) prints its traceback only into this output.
  local status=0
  # shellcheck disable=SC2086 # PYTEST_TARGETS is a list of paths
  uv run --no-sync pytest ${PYTEST_TARGETS:-} 2>&1 | tee "${SHARD_LOG:-pytest-shard.log}" || status=$?
  [ "$status" -eq 0 ] || { [ "$status" -eq 5 ] && [ -n "${PYTEST_TARGETS:-}" ]; }
}

# ci.yml fans the suite out over runners and reads the verdict here: SELECT_RESULT and SHARDS_RESULT are the `select` and
# `python-shard` jobs' results, LAUNCHED the shard indexes `select` launched. It passes when `select` did and every shard
# did, or when none launched because no test was selected; a shard that failed, was cancelled or never ran fails it.
cmd_python_verdict() {
  test "$SELECT_RESULT" = success
  test "${SHARDS_RESULT:-}" = success || { test "${SHARDS_RESULT:-}" = skipped && test "${LAUNCHED:-}" = '[]'; }
}

# The whole context on this machine: select, then every selected test in one unsharded run.
cmd_python() {
  if [ -n "${SELECT_RESULT:-}" ]; then
    cmd_python_verdict
    return
  fi
  local selected targets shards
  selected=$(cmd_select)
  targets=$(sed -n 's/^PYTEST_TARGETS=//p' <<<"$selected")
  shards=$(sed -n 's/^PYTEST_SHARDS=//p' <<<"$selected")
  if [ "$shards" = '[]' ]; then
    echo "no test selected"
    return
  fi
  PYTEST_TARGETS=$targets cmd_python_shard
}

cmd_web() {
  pnpm --dir starpulse/web install --frozen-lockfile
  pnpm --dir starpulse/web run check
}

cmd_static_checks() {
  bash ci/static_checks.sh
}

# The release build without publishing (release.yml's `build`): the page, then the wheel that must ship it. It builds in a
# scratch checkout: vite empties starpulse/static, which the python shards of the same sp-ci clone read while they run.
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
  select | python-shard | python | web | static-checks | build)
    "cmd_${1//-/_}"
    ;;
  *)
    echo "usage: ci/run.sh python|web|static-checks|build (or select|python-shard)" >&2
    exit 2
    ;;
esac
