#!/usr/bin/env bash
# The short static checks, run at once in one job so a merge-queue run takes one validate runner for them, not four:
# the job's wall time is its slowest check (api-types), not their sum. Each check logs to its own file, printed as a
# group when all have finished; one that fails is named and fails the job, and the others still run to completion.
# shellcheck disable=SC2317 # the checks are invoked through "$check"
set -uo pipefail

logs=$(mktemp -d)

# An IC instance runs without the hub extras: import every module it can load on an environment that holds neither the
# Postgres driver, Alembic nor the container tooling. Its own environment keeps api-types' full one intact.
ic() {
  export UV_PROJECT_ENVIRONMENT="${RUNNER_TEMP:-$logs}/ic-venv"
  uv sync --locked --no-group hub &&
    uv run --no-sync python -c "import importlib.util as u, sys; sys.exit(any(u.find_spec(m) for m in ('alembic', 'psycopg', 'jwt', 'testcontainers')))" &&
    uv run --no-sync python ci/ic_imports.py
}

# This repository is public: no tracked file outside the workflows and tests may name the operator's private hosts.
public_names() {
  uv run --no-project --python 3.14 python ci/public_names.py
}

# The page's API types are generated from starpulse/contracts/api.py: regenerate both outputs, fail when either differs.
api_types() {
  uv sync --locked &&
    pnpm --dir starpulse/web install --frozen-lockfile &&
    uv run --no-sync python -m starpulse.contracts.api &&
    pnpm --dir starpulse/web run gen:types &&
    git diff --exit-code -- starpulse/api.schema.json starpulse/web/src/api/types.gen.ts
}

# trantor's check-config test-tier policy over this tree, with trantor's lib checked out at .trantor. GIT_CLI_LIST_TIMEOUT
# is read by git_cli.list_timeout: unset is the fail-sentinel 0 and times out ls-files immediately.
tier_policy() {
  PYTHONPATH=.trantor/lib GIT_CLI_LIST_TIMEOUT=60 uv run --no-project --python 3.14 --with pyyaml \
    python ci/trantor_tier_policy.py .trantor/lib/linting/check_config_checks/tier_policy.py
}

checks=(api_types ic public_names tier_policy)
pids=()
for check in "${checks[@]}"; do
  "$check" >"$logs/$check.log" 2>&1 &
  pids+=($!)
done

status=0
for i in "${!checks[@]}"; do
  name=${checks[$i]//_/-}
  if wait "${pids[$i]}"; then outcome=passed; else outcome=failed status=1; fi
  echo "::group::$name $outcome"
  cat "$logs/${checks[$i]}.log"
  echo "::endgroup::"
  [ "$outcome" = failed ] && echo "static check failed: $name"
done
exit "$status"
