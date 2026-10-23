<p align="center">
  <a href="https://trantor-org.github.io/starpulse/main/starpulse.html"><img src="https://trantor-org.github.io/starpulse/main/starpulse-star-map.png" alt="StarPulse's star map: tasks, workflow runs and agents moving live" width="900"></a>
</p>

<h1 align="center">StarPulse</h1>

<p align="center"><strong>Every task, workflow run and agent in flight, on one live page.</strong></p>

<p align="center">
  <a href="https://github.com/trantor-org/starpulse/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/trantor-org/starpulse/ci.yml?branch=main&style=flat-square&label=ci" alt="CI status"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/v/starpulse?style=flat-square&label=pypi" alt="PyPI version"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/pyversions/starpulse?style=flat-square" alt="Python version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://trantor-org.github.io/starpulse/main/starpulse.html">Live demo</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/serving.md">Configure</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/sources.md">Sources</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/cli.md">Agent CLI</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/adapters.md">Adapters</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/consumers.md">Consumers</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/security.md">Security</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/public-surface.md">Compatibility</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/development-loop.md">Development loop</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

## What it is and why

I wanted to see where my agents were in their sessions and which skills they
were using. Then I watched a video that mapped agent actions onto state
machines, and I wanted to map the whole agent lifecycle and pair it with the
Dagu workflows I already run, so scripts and DAGs could take over manual AI
commands and cut the step count.

StarPulse is what I built. It shows tasks, workflow runs and agents on one live
page. It produces data and leaves what to do with that data to you. It is not
tied to one agent harness or one lifecycle: you define the states, and it draws
and records them.

## Quick start

```sh
uvx starpulse init    # writes starpulse.toml, board.yaml, .starpulse/board/ and .claude/settings.json (--harness, --dir)
export STARPULSE_TOKEN=$(openssl rand -hex 16)
uvx starpulse serve   # then open http://localhost:8766
```

`init` scaffolds a board machine with its roles declared, a `[[board.guards]]` rule, a `[scheduler]` table, a producer
whose token is read from `STARPULSE_TOKEN`, and the Claude Code telemetry export settings; it refuses to overwrite an
existing file. The board starts empty, with the lanes the machine's states name, ready for `uvx starpulse task create`.

### Working with AI agents

An agent works the board through the `starpulse` CLI, every verb printing JSON ([Agent CLI](https://github.com/trantor-org/starpulse/blob/main/docs/cli.md)). `uvx starpulse skills install --claude --codex` copies the bundled skills into the project. For any other agent, add a section to `AGENTS.md` or `CLAUDE.md`:

```md
## Tasks

This project tracks work on a StarPulse board. Run `uvx starpulse help --agent` for every verb, its
arguments and exit codes. Read the board with `uvx starpulse board` and open a task with
`uvx starpulse task create "<title>"`.
```

### Working without AI agents

The same verbs work typed by hand, and **New task** on the Kanban adds a task from the page. Both write the same board.

## Views

| Kanban | Star Map | Workflow runs |
|---|---|---|
| <img src="https://trantor-org.github.io/starpulse/main/starpulse-kanban.png" alt="Kanban view"> | <img src="https://trantor-org.github.io/starpulse/main/starpulse-star-map.png" alt="Star Map view"> | <img src="https://trantor-org.github.io/starpulse/main/starpulse-dags.png" alt="Workflow runs view"> |

Reads tasks from its own Markdown board, Backlog.md or Jira; runs from Dagu, GitHub Actions or systemd; agents from Claude Code and Copilot.

## Status

StarPulse is early. This is my first open source project, and I am still
learning how to run one. What is rough today:

- The UI is messy and not fully implemented.
- The data it captures is not yet acted on in full; the feedback loop from
  captured signal to changed behavior is incomplete.
- Performance is good but could be better.

## Feedback

Something broke, confused you or is missing? [Open an issue](https://github.com/trantor-org/starpulse/issues/new).
Say what you ran and what you expected. A confusing first run is a bug I want to
hear about.

MIT licensed.
