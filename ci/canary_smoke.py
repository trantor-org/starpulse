"""Canary smoke: boot StarPulse against a copy of live state and check its happy path.

Usage: canary_smoke.py --url URL --config PATH --machines DIR --db PATH

The steps run in order: migrate the store to the wheel's head, serve, `starpulse reload` exits 0, the workers hold
for HOLD seconds without restarting, then the board renders and a task modal opens. --db is a copy (`VACUUM INTO` of
the live store) that migrate writes in place; the live file is never passed. A failed step prints `<step>: <problem>`
and exits 1.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from fresh_serve import LOG_TAIL, check, live_children, worker_contexts
from sqlalchemy import create_engine
from starpulse._internal.eventlog.migrate import migrate

DEADLINE = 60.0
HOLD = 60.0
SAMPLE = 5.0
BROWSER_MS = 15_000
DATABASE_URL = re.compile(r"^database_url = .*$", re.MULTILINE)
SECTION = re.compile(r"^\[+([\w.]+)\]+\s*$")
ENTRY = re.compile(r'^(\w+) = "([^"]+)"\s*$')
ENV_NAME = re.compile(r'^\w*_env = "(\w+)"', re.MULTILINE)
# (section, key) of each relative path: "" is the top level. Reads resolve against the live config's directory.
READS = {("", "harnesses_file"), ("board", "path"), ("board", "machine")}
WRITES = {("", "event_log_archive_dir"), ("scheduler", "state_dir")}
# (section, key) of each board command. The canary drops them: `holds --record-evidence` writes comments to the live board.
COMMANDS = {("board", "criteria"), ("board", "holds")}


def render_config(config: str, db: Path) -> str:
    """The config with `database_url` pointed at the copy."""
    line = f'database_url = "sqlite:///{db}"'
    if DATABASE_URL.search(config):
        return DATABASE_URL.sub(lambda _: line, config)
    return f"{config}\n{line}\n"


def anchor_paths(config: str, live: Path, scratch: Path) -> str:
    """The config with its relative paths resolved: reads against the live config dir, writes into the scratch tree.

    `state_dir` holds the autopilot switch, so a canary that reads it could start sessions; it must never see live state.
    Board commands are dropped, so the canary never runs a live script.
    """
    section = ""
    lines = []
    for line in config.splitlines():
        if header := SECTION.match(line):
            section = header.group(1)
        elif (entry := ENTRY.match(line)) and (section, entry.group(1)) in COMMANDS:
            continue
        elif (entry := ENTRY.match(line)) and (section, entry.group(1)) in READS | WRITES:
            key, value = entry.groups()
            base = live if (section, key) in READS else scratch
            line = f'{key} = "{Path(os.path.normpath(base / value))}"'
        lines.append(line)
    return "\n".join(lines) + "\n"


def step_migrate(db: Path) -> str | None:
    """None when migrate brings the copy to the wheel's head, else why it could not (alembic refuses a revision it does not know)."""
    engine = create_engine(f"sqlite:///{db}")
    try:
        migrate(engine)
    except Exception as error:
        return f"migrate: {error}"
    finally:
        engine.dispose()
    return None


def wait_ready(serve: subprocess.Popen[bytes], port: int, expected: set[str], log: Path) -> str | None:
    """None once the page answers 200 with every expected worker alive, else the last problem within DEADLINE."""
    problem = "serve did not start"
    end = time.monotonic() + DEADLINE
    while time.monotonic() < end and serve.poll() is None:
        if (problem := check(port, serve.pid, expected, log)) is None:
            return None
        time.sleep(0.5)
    return f"serve: {problem}" if serve.poll() is None else f"serve: exited {serve.returncode}"


def hold(serve: subprocess.Popen[bytes], port: int, expected: set[str], log: Path) -> str | None:
    """None when the same workers stay alive and the page keeps answering for HOLD seconds."""
    before = live_children(serve.pid, log)
    end = time.monotonic() + HOLD
    while time.monotonic() < end:
        time.sleep(SAMPLE)
        if serve.poll() is not None:
            return f"hold: serve exited {serve.returncode} within {HOLD:.0f}s"
        if live_children(serve.pid, log) != before:
            return f"hold: a child restarted within {HOLD:.0f}s"
    return None if (problem := check(port, serve.pid, expected, log)) is None else f"hold: {problem}"


def step_reload(python: str, root: Path, config: Path, environ: dict[str, str]) -> str | None:
    """None when `starpulse reload` exits 0 against the running supervisor."""
    done = subprocess.run(
        [python, "-m", "starpulse", "reload", "--config", str(config)],
        cwd=root,
        env=environ,
        capture_output=True,
        text=True,
    )
    if done.returncode:
        return f"reload: exited {done.returncode}: {(done.stdout + done.stderr)[-LOG_TAIL:]}"
    return None


def step_board(url: str) -> str | None:
    """None when the board renders its cards and the first card's task modal opens labelled with its id."""
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(f"{url}/?view=kanban", timeout=BROWSER_MS)
            card = page.locator("#cols .card").first
            card.wait_for(timeout=BROWSER_MS)
            task = card.get_attribute("data-id")
            if not task:
                return "board: first card has no data-id"
            card.click()
            dialog = page.get_by_role("dialog")
            dialog.wait_for(timeout=BROWSER_MS)
            label = dialog.get_attribute("aria-label") or ""
            if not label.startswith(task):
                return f"board: modal labelled {label!r}, not {task!r}"
        except Error as error:
            return f"board: {error}"
        finally:
            browser.close()
    return None


def env(root: Path, config: str) -> dict[str, str]:
    """The environment `serve` and reload run in: no secrets and nothing from the checkout.

    Each variable the config names for a token is set to its own placeholder: `serve` refuses to start without them and
    refuses two producers sharing one, and the canary never calls a producer, so a placeholder authenticates nothing.
    """
    placeholders = {name: f"canary-placeholder-{name.lower()}" for name in ENV_NAME.findall(config)}
    return {"PATH": os.environ["PATH"], "HOME": str(root), **placeholders}


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Boot StarPulse against a copy of live state and check its happy path.")
    cli.add_argument("--url", required=True, help="base URL serve binds, with its port")
    cli.add_argument("--config", required=True, help="the live starpulse.toml; database_url is replaced")
    cli.add_argument("--machines", required=True, help="the live .starpulse/machines directory")
    cli.add_argument("--db", required=True, help="a copy of the live store, migrated in place")
    return cli


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    url = urlsplit(args.url)
    db = Path(args.db).resolve()
    if problem := step_migrate(db):
        print(problem)
        return 1
    python = sys.executable
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        config = root / "starpulse.toml"
        live = Path(args.config).resolve()
        anchored = anchor_paths(live.read_text(), live.parent, root)
        config.write_text(render_config(anchored, db))
        shutil.copytree(args.machines, root / ".starpulse" / "machines")
        environ = env(root, anchored)
        expected = worker_contexts(python, str(root))
        log = root / "serve.log"
        with log.open("w") as sink:
            serve = subprocess.Popen(
                [python, "-m", "starpulse", "serve", "--host", url.hostname, "--port", str(url.port), "--config", str(config)],
                cwd=root,
                env=environ,
                stderr=sink,
            )
        try:
            if problem := wait_ready(serve, url.port, expected, log):
                print(f"{problem}\n--- serve stderr ---\n{log.read_text()[-LOG_TAIL:]}")
                return 1
            if problem := step_reload(python, root, config, environ):
                print(problem)
                return 1
            if problem := hold(serve, url.port, expected, log):
                print(problem)
                return 1
            if problem := step_board(args.url):
                print(problem)
                return 1
        finally:
            serve.terminate()
            try:
                serve.wait(10)
            except subprocess.TimeoutExpired:
                serve.kill()
    print("ok: migrate, serve, reload, hold and board")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
