<p align="center">
  <a href="https://trantor-org.github.io/starpulse/main/starpulse.html"><img src="https://trantor-org.github.io/starpulse/main/starpulse-star-map.png" alt="StarPulse's star map: tasks, workflow runs and agents moving live" width="900"></a>
</p>

<h1 align="center">StarPulse</h1>

<p align="center"><strong>Declarative state machines for agent work, with an enforced task board and a live view of every task, workflow run and agent session.</strong></p>

<p align="center">
  <a href="https://github.com/trantor-org/starpulse/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/trantor-org/starpulse/ci.yml?branch=main&style=flat-square&label=ci" alt="CI status"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/v/starpulse?style=flat-square&label=pypi" alt="PyPI version"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/pyversions/starpulse?style=flat-square" alt="Python version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://trantor-org.github.io/starpulse/main/starpulse.html">Live demo</a> ·
  <a href="docs/serving.md">Documentation</a> ·
  <a href="docs/cli.md">CLI reference</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

StarPulse models each lifecycle in a project (a task board, a delivery pipeline, a skill's steps, a pull request's CI)
as a state machine declared in YAML: its states, its transitions, and which writers (the operator, an agent, a named
workflow) may make each move. Every move is recorded against its machine in an append-only event store and refused when
the machine forbids it, whether it arrives from the CLI, the HTTP API or the web UI. A single page draws every machine
live, with tasks, workflow runs and agent sessions moving through it.

## Highlights

- **Machines as data.** Lifecycles, guards and writer permissions are declared in YAML and validated with
  `starpulse machine validate`; a Kanban board is one machine, its states rendered as lanes.
- **Enforced writes.** One write path for the CLI, the API and the page; a forbidden transition is refused, not drawn.
- **Event-sourced state.** Append-only streams with optimistic concurrency, a transactional outbox and schema
  upcasters, in a single portable SQLite database.
- **Agent-native CLI.** Every verb prints JSON with documented exit codes; `starpulse help --agent` emits the full verb
  manifest for an agent's context.
- **Pluggable sources.** Adapters for task trackers, workflow schedulers and agent harnesses, plus a CloudEvents
  ingest (HTTP and gRPC) for anything else.
- **Built-in scheduler.** Admission, quiet hours and dispatch of Ready tasks to agent sessions.
- **Observable.** Prometheus `/metrics`, OTLP intake for agent telemetry, and flow and session analytics.

## Why StarPulse

Most issue trackers treat a status as a label: anyone, or any agent, can drag a card to any column. StarPulse treats a task's lifecycle as a state machine you declare, and it is built for boards that AI agents work through.

- **Moves are enforced, not just drawn.** States, transitions and which writers may make each move live in YAML. `[[board.guards]]` rules add record-level conditions, for example "Done needs a pull request in references". A forbidden move is refused the same way from the CLI, the HTTP API and the web page, with a reason and the skill that satisfies it. `starpulse conform` replays recorded history against the declared machines and prints each violation.
- **A scheduler that dispatches work to agents.** The built-in scheduler admits Ready tasks into agent sessions, with admission limits and quiet hours, so agents pull work from the board instead of waiting to be assigned.
- **Paused work says why.** A paused task sits in Waiting when it is blocked on something specific, or in Needs attention when a person has to act, with the reason recorded on the task.
- **Every change is an event.** State lives in append-only, event-sourced streams with optimistic concurrency and a transactional outbox, in one portable SQLite database. Prometheus `/metrics`, OTLP agent telemetry and flow and session analytics sit on top of that record.
- **One model for agents, code and workflows.** A task board, a delivery pipeline, a skill's steps and a pull request's CI are all machines. Agents, workflow schedulers such as Dagu or GitHub Actions, and plain code move them through the same enforced write path.
- **Yours to run.** Install it with `uv tool install starpulse` or `pipx install starpulse` and run `starpulse serve`. There is no hosted service and no per-seat pricing; `serve` supervises its own workers, and your board is files and a database you own.

### Compared with a hosted tracker

| | Typical hosted tracker | StarPulse |
|---|---|---|
| Where it runs | The vendor's cloud | Your machine, installed from PyPI |
| Cost | Usually per seat | Free and open source (MIT) |
| Status changes | Free-form; anyone can move anything | Declared machines and guards; refused moves are never written |
| Agent work | Agents act when a person assigns or mentions them | The scheduler admits Ready tasks into agent sessions |
| History | An activity feed | An append-only event log that guards and analytics replay |

Hosted tools such as Linear have polished planning features (cycles, projects, triage) and their own agent platform, where you assign an issue to an agent or @mention it. StarPulse doesn't try to replace that. It is for teams that want the board to enforce the process their agents follow.

## Installation

StarPulse requires Python 3.14 or later.

Install from a GitHub Release; the PyPI versions are old and no longer maintained.

### Install from a GitHub Release

New versions are published as GitHub Releases, not to PyPI. Each
Release carries the versioned wheel, `starpulse-latest-py3-none-any.whl` (the same wheel under a name that never
changes) and `starpulse-web.tar.gz` (the built web page). The latest Release's fixed URL is
`https://github.com/trantor-org/starpulse/releases/latest/download/starpulse-latest-py3-none-any.whl`.
Installers read the version from a wheel's file name and `latest` is not a version, so fetch the wheel by that URL and
install the copy under its own name:

```sh
dir=$(mktemp -d)
curl -fsSL -o "$dir/starpulse-latest-py3-none-any.whl" \
  https://github.com/trantor-org/starpulse/releases/latest/download/starpulse-latest-py3-none-any.whl
name=$(python3 -c "import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); print(next(n for n in z.namelist() if n.endswith('/WHEEL')).split('/')[0][:-len('.dist-info')])" "$dir/starpulse-latest-py3-none-any.whl")
mv "$dir/starpulse-latest-py3-none-any.whl" "$dir/$name-py3-none-any.whl"
uv tool install "$dir/$name-py3-none-any.whl"
```

## Quick start

```sh
starpulse init                                  # scaffold starpulse.toml, board.yaml and .starpulse/board/
export STARPULSE_TOKEN=$(openssl rand -hex 16)  # producer token read by the scaffolded config
starpulse serve                                 # open http://localhost:8766
starpulse task create "First task"
```

`init` writes a board machine with its roles declared, an example `[[board.guards]]` rule, a `[scheduler]` table and
Claude Code telemetry export settings (`--harness`, `--dir` to change them). It never overwrites an existing file.
`starpulse doctor` checks the config, the server and each adapter.

## Using StarPulse with agents

Install the bundled skills into a project:

```sh
starpulse skills install --claude --codex
```

For any other harness, point the agent at the CLI from `AGENTS.md` or `CLAUDE.md`:

```md
## Tasks

This project tracks work on a StarPulse board. Run `uvx starpulse help --agent` for every verb, its
arguments and exit codes. Read the board with `uvx starpulse board` and open a task with
`uvx starpulse task create "<title>"`.
```

The same verbs work by hand, and **New task** on the Kanban view writes to the same board.

## Integrations

| Kind | Supported |
|---|---|
| Task trackers | Native Markdown board, Backlog.md, Jira |
| Workflow runs | Dagu, GitHub Actions, systemd timers, any scheduler via CloudEvents |
| Agent sessions | Claude Code (OTLP), GitHub Copilot cloud agent and code review |

New trackers and producers are written against the board, machine-events and runs contracts; see
[Adapters](docs/adapters.md).

## Views

| Kanban | Star Map | Workflow runs |
|---|---|---|
| <img src="https://trantor-org.github.io/starpulse/main/starpulse-kanban.png" alt="Kanban view"> | <img src="https://trantor-org.github.io/starpulse/main/starpulse-star-map.png" alt="Star Map view"> | <img src="https://trantor-org.github.io/starpulse/main/starpulse-dags.png" alt="Workflow runs view"> |

## Documentation

| Guide | Covers |
|---|---|
| [Serve and configure](docs/serving.md) | Server, workers, config file, event store, scheduler, releases |
| [Connect sources](docs/sources.md) | Agent telemetry, runs adapters, CloudEvents ingest, pull requests |
| [CLI reference](docs/cli.md) | Every verb, its arguments, JSON output and exit codes |
| [Write an adapter](docs/adapters.md) | Board, machine-events and runs contracts, and the adapter kit |
| [Build a consumer](docs/consumers.md) | Dashboards, alerts and reports built on the event log export |
| [Security](docs/security.md) | Network exposure, request checks and the trust model |
| [Compatibility](docs/public-surface.md) | The public surface and how releases keep it compatible |
| [Development](docs/development.md) | Building and testing StarPulse from source |
| [Development loop](docs/development-loop.md) | How StarPulse fits a workflow with many concurrent agent sessions |

## Status

StarPulse is pre-1.0 and under active development; minor releases may change the config, CLI and API. The
[public surface](docs/public-surface.md) lists what is covered by compatibility guarantees. Known gaps:

- Parts of the web UI are incomplete.
- Captured signals are recorded and reported but not yet fed back into scheduling decisions.

## Contributing

Bug reports and pull requests are welcome. Open an [issue](https://github.com/trantor-org/starpulse/issues/new) with
the command you ran and what you expected, and read [CONTRIBUTING.md](CONTRIBUTING.md) before sending a change.

## License

[MIT](LICENSE)
