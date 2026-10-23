#!/usr/bin/env bash
# The latency budget (StarPulse Holds a Latency Budget on Every Request and Frame): builds the page, serves the seeded demo
# on a free port and times every surface three times with bench/page_latency.py, judging the median run's p95 against the
# 50 ms budget. Exits with the harness's status: 1 on a row over budget or a non-2xx request row.
# Run from the repository root. Pull requests do not run it (it was the slowest job on each); trantor's nightly
# `starpulse-latency` Dagu DAG clones main and runs it on a dedicated worker, and fails the whole-repo gate on a miss.
# The board's first paint holds a 450 ms ceiling: startup JavaScript, not server time, keeps it over 50 ms on shared hardware.
set -euo pipefail

work="$(mktemp -d)"
server=
trap '[ -z "$server" ] || kill "$server" 2>/dev/null || true; rm -rf "$work"' EXIT

(cd starpulse/web && pnpm install --frozen-lockfile && pnpm run build)
uv sync --locked --group bench

port="$(uv run --no-sync python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
uv run --no-sync python -m ci.seeded_server --port "$port" --dir "$work" >"$work/server.log" 2>&1 &
server=$!

ready=false
for _ in $(seq 1 150); do
  if curl -sf --connect-timeout 2 --max-time 5 -o /dev/null "http://127.0.0.1:$port/api/snapshot"; then
    ready=true
    break
  fi
  kill -0 "$server" 2>/dev/null || break
  sleep 2
done
if [ "$ready" != true ]; then
  cat "$work/server.log"
  exit 1
fi

uv run --no-sync python bench/page_latency.py "http://127.0.0.1:$port" --repeat 3 \
  --ceiling "first paint of the board=450" --fail-non-2xx
