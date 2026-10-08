---
name: setting-up-starpulse
description: Gets StarPulse running and checks that an install works. Use when asked to set up, start or configure StarPulse, to connect a Postgres history, a runs adapter or Claude Code session telemetry, or when a starpulse command reports the server is unreachable.
---

# Setting Up StarPulse

StarPulse needs `uv`. Run it from the project whose work it should draw.

## Start and verify

1. Run `uvx starpulse serve`. The page is at `http://localhost:8766`; `--port` and `--hours` change the port and how
   far back a task's latest move counts.
2. Run `starpulse doctor`. It reports `ok` and one `{check, status, reason}` per check, runs every check even after a
   failure and exits 1 when any fails.
3. Fix each failing `reason`, then run `starpulse doctor` again.

Done when `ok` is true. Checks: `config`, `server`, `adapter:board` (and `adapter:<name>` per runs instance), and `gh`.

## Config

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read when
it exists. Keys: `tracker_url`, `database_url` (Postgres history, installed with `uvx --from 'starpulse[postgres]'
starpulse serve`), `[board]` with `type`, and one `[[runs]]` table per runs adapter with `name`, `type`, `url`. SQLite
must be on a local disk; set `database_url` to Postgres when the config or project lives on NFS or SMB. Run `starpulse
doctor --config starpulse.toml` after an edit.

## Show Claude Code sessions

1. Run the receiver beside the server: `uvx --from starpulse python -m starpulse.claude_code`.
2. Start Claude Code with `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_LOGS_EXPORTER=otlp`,
   `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318`,
   `OTEL_LOG_TOOL_DETAILS=1` and `OTEL_RESOURCE_ATTRIBUTES="vcs.ref.head.name=$(git branch --show-current)"`.

Done when the session appears on the page.

Verbs read the server at `--server`, else `STARPULSE_URL`, else `http://localhost:8766`. A hub
answers 401 until signed in: set `STARPULSE_TOKEN` to its reader token (`reader_token_env`) to read it.
