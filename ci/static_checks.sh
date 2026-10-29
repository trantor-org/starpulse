#!/usr/bin/env bash
# The short static checks, run at once in one job so a run takes one runner for them, not five:
# the job's wall time is its slowest check (api-types), not their sum. Each check logs to its own file, printed as a
# group when all have finished; one that fails is named and fails the job, and the others still run to completion.
# shellcheck disable=SC2317 # the checks are invoked through "$check"
set -uo pipefail

logs=$(mktemp -d)

# This repository is public: no tracked file outside the workflows and tests may name the operator's private hosts.
public_names() {
  uv run --no-project --python 3.14 python ci/public_names.py
}

# The page's API types are generated from starpulse/contracts/api/: regenerate both outputs, fail when either differs.
api_types() {
  pnpm --dir starpulse/web install --frozen-lockfile &&
    uv run --no-sync python -m starpulse.contracts.api &&
    pnpm --dir starpulse/web run gen:types &&
    git diff --exit-code -- starpulse/schemas/api.schema.json starpulse/web/src/api/types.gen.ts
}

# The settings reference in docs/serving.md is generated from starpulse/runtime/config_model.py: regenerate it, fail on a diff.
config_reference() {
  uv run --no-sync python -m starpulse.runtime.config_reference &&
    git diff --exit-code -- docs/serving.md
}

# The checked-in protobuf modules are generated from the .proto files beside them: regenerate them, fail when one differs.
wire_pb2() {
  uv run --no-sync python -m grpc_tools.protoc -I. --python_out=. --pyi_out=. \
    starpulse/runs/wire/ingest.proto starpulse/runs/wire/cloudevents.proto &&
    git diff --exit-code -- starpulse/runs/wire
}

# The import tiers in pyproject.toml: `lint-imports` fails when a module imports across a layer it may not. It runs here, beside
# the other short checks, so `select` does not hold every shard back for it.
import_layers() {
  uv run --no-sync lint-imports
}

# `uv sync` creates .venv, which the checks below read: it runs once here, before any of them starts, so no two uv
# invocations race to create .venv/bin (a concurrent sync once broke a check with a missing .venv/bin temp file).
uv sync --locked || exit 1

checks=(api_types public_names config_reference wire_pb2 import_layers)
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
