"""`starpulse init`: scaffold a first install in a directory, then `starpulse serve` runs it.

    starpulse init                        # Claude Code, in the current directory
    starpulse init --dir demo --harness claude-code

Writes `starpulse.toml` (a native `[board]` with one `[[board.guards]]` rule, a `[scheduler]` table and a `[[producers]]`
entry whose token is read from `STARPULSE_TOKEN`), `board.yaml` (a four-State machine with every role declared), `.starpulse/board/config.yml` (the board's lanes, the
machine's States), an empty `tasks/` and the harness's telemetry export settings (`.claude/settings.json` for Claude Code, so its sessions reach the OTLP receiver
and link to the Tasks they claim). It writes nothing when any of them exists, says which on stderr and exits 1; it
never writes a token.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONFIG = """\
[board]
type = "native"
path = ".starpulse/board"
machine = "board.yaml"

[[board.guards]]
on = { to = "review" }
require = { field = { field = "references", matches = "/pull/\\\\d+$", min = 1 } }
reason = "Review needs a pull request in references"

[scheduler]

# The producer that posts machine events and runs; set STARPULSE_TOKEN in the server's environment.
[[producers]]
name = "HARNESS"
token_env = "STARPULSE_TOKEN"
"""

MACHINE = """\
name: board
states:
  backlog: {initial: true}
  in_progress: {role: resting}
  review: {role: waiting_on_person}
  done: {final: true}
events:
  START: [{from: backlog, to: in_progress}]
  REVIEW: [{from: in_progress, to: review}]
  REWORK: [{from: review, to: in_progress}]
  FINISH: [{from: review, to: done}]
"""

#: The board's lanes, spelled as `MACHINE`'s States: the native board refuses to open when the two disagree.
BOARD_CONFIG = """\
project_name: demo
statuses: [Backlog, In Progress, Review, Done]
task_prefix: task
"""

CLAUDE_CODE_TELEMETRY = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
    "OTEL_LOG_TOOL_DETAILS": "1",
}

#: Each harness's telemetry settings file, relative to the install, and the `env` it sets.
TELEMETRY = {"claude-code": (Path(".claude") / "settings.json", CLAUDE_CODE_TELEMETRY)}


def _files(harness: str) -> dict[Path, str]:
    settings, env = TELEMETRY[harness]
    return {
        Path("starpulse.toml"): CONFIG.replace("HARNESS", harness),
        Path("board.yaml"): MACHINE,
        Path(".starpulse") / "board" / "config.yml": BOARD_CONFIG,
        Path(".starpulse") / "board" / "tasks" / ".gitkeep": "",
        settings: json.dumps({"env": env}, indent=2) + "\n",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="starpulse init", description="scaffold a first StarPulse install")
    parser.add_argument("--dir", type=Path, default=Path(), help="the directory to scaffold (default .)")
    parser.add_argument(
        "--harness", choices=sorted(TELEMETRY), default="claude-code", help="the harness to export telemetry from"
    )
    args = parser.parse_args(argv)

    files = {args.dir / name: text for name, text in _files(args.harness).items()}
    existing = [str(path) for path in files if path.exists()]
    if existing:
        print(f"starpulse init: {', '.join(existing)} already exists; nothing written", file=sys.stderr)
        return 1
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    print(f"wrote {', '.join(str(path) for path in files)}; set STARPULSE_TOKEN, then run `starpulse serve`")
    return 0
