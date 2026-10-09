# StarPulse — see the flow of work on one page

<p align="center">
  <a href="https://github.com/trantor-org/starpulse/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/trantor-org/starpulse/ci.yml?branch=main&style=flat-square&label=ci" alt="CI status"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/v/starpulse?style=flat-square&label=pypi" alt="PyPI version"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/pyversions/starpulse?style=flat-square" alt="Python version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License: MIT"></a>
</p>

StarPulse draws your scheduler's workflows, the lifecycle your tasks move through, and the agents and people moving
them, live on one page. Each board status is a state on a machine and a task travels its transitions as it moves;
every move is kept, so hovering a task traces the path it took.

**[Live demo](https://trantor-org.github.io/starpulse-demo/main/flow-view.html)**: a demo board with synthetic tasks,
running in your browser with no server.

[Docs](https://github.com/trantor-org/starpulse/tree/main/docs) · [Agent CLI](https://github.com/trantor-org/starpulse/blob/main/docs/cli.md) · [Configuration](https://github.com/trantor-org/starpulse/blob/main/docs/serving.md) · [Releases](https://github.com/trantor-org/starpulse/releases) · [Issues](https://github.com/trantor-org/starpulse/issues/new/choose)

## Install

You need [uv](https://docs.astral.sh/uv/) and Python 3.14+. StarPulse is published to PyPI as `starpulse`; `uvx`
runs it without installing:

```sh
uvx starpulse serve
```

Add `starpulse[postgres]` for history in Postgres, or `starpulse[hub]` to run a hub.

## Quick start

```sh
cd your-project
uvx starpulse serve
```

Open <http://localhost:8766>. The first serve creates an empty Markdown board under `.starpulse/board/`; **New task**
adds a task, and **Connect a tracker** points the page at a [Backlog.md](https://github.com/MrLesk/Backlog.md) or
Jira project instead (`starpulse connect backlog --path backlog`). Then check the install:

```sh
uvx starpulse doctor
```

See [Serve and configure](https://github.com/trantor-org/starpulse/blob/main/docs/serving.md) for the port, the
history window, the config file and every tracker.

## How it fits together

- **Board.** Tasks on their lifecycle machine, from StarPulse's own Markdown board, Backlog.md or Jira, with a Kanban
  view whose moves are written back when the adapter has a writer.
- **Workflow runs.** Each workflow drawn as its step graph with its latest run: [Dagu](https://github.com/dagu-org/dagu),
  GitHub Actions and systemd timers are read directly; any other scheduler reports with `starpulse emit`.
- **Agents at work.** A Claude Code session's OpenTelemetry log export moves the session through its own machine.
- **Pull requests and Copilot.** Pull requests move through checks to merge; Copilot's coding agent and reviews move
  through their own machine.
- **Hub.** Instances forward their events to a Postgres-backed hub behind OpenID Connect, which draws one level above
  the Board as a Flow graph.

An agent works the board through the [`starpulse` command line](https://github.com/trantor-org/starpulse/blob/main/docs/cli.md),
whose every verb prints one JSON document.

## Security

The page has no sign-in and listens on `127.0.0.1` only; `--host 0.0.0.0` exposes it to your network, which you do
only on a network you trust. A write is refused unless it is a JSON request with no `Origin` or this server's own, so
another site cannot write through your browser. `/api/move` is unauthenticated on the LAN: machine `writers` stop an
agent's accident, not an adversary.

The Claude Code receiver publishes which session moved, on which event and when; prompt, reply and tool text is
neither stored nor forwarded. Forwarding to a hub keeps `actor` and `assignee` at home unless the instance opts in.
A hub refuses to start without an `[oidc]` table. See [Run a hub](https://github.com/trantor-org/starpulse/blob/main/docs/hub.md)
before exposing one.

## Documentation

| Goal | Start here |
|---|---|
| Serve, configure, connect a tracker | [Serve and configure](https://github.com/trantor-org/starpulse/blob/main/docs/serving.md) |
| Show agents, scheduler runs and pull requests | [Connect sources](https://github.com/trantor-org/starpulse/blob/main/docs/sources.md) |
| Work the board from an agent | [Agent command line](https://github.com/trantor-org/starpulse/blob/main/docs/cli.md) |
| Run a hub, a level, engines and forwarding | [Run a hub](https://github.com/trantor-org/starpulse/blob/main/docs/hub.md) |
| Connect your own tracker | [Write a board adapter](https://github.com/trantor-org/starpulse/blob/main/docs/adapters.md) |
| Build, test and benchmark StarPulse | [Development](https://github.com/trantor-org/starpulse/blob/main/docs/development.md) |

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes.
- The documented entry point `python -m starpulse.claude_code`.
- The config file's keys and the machine YAML with its JSON Schema (`machine.schema.json`).

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written`, the writer, task, milestone and doc protocols, and the `UpstreamBacklog` reference adapter).
- `starpulse.board_feed`: the feed a board adapter places tasks on (`BoardFeed`) and what following a stream needs of it.
- `starpulse.contracts`: the board, machine-event, runs (`Dag`, `RecentRun`) and insights (`Finding`) records, their JSON Schemas, and `RunsSink`.
- `starpulse.adapter_kit`: the test kit an adapter or insights engine author runs against their work, and the helpers that serve it.
- `starpulse.machine_definition`: loading and validating a machine, and the `Registry` of guards and actions.
- `starpulse.snapshot`: how a machine is described to the page, and how its workflows are named.
- `starpulse.history`: the history a board adapter may keep itself, and placing a task's events on a machine.
- `starpulse.event_log`: the database event log producers append to and readers tail.
- `starpulse.config`: loading the config file, and the runs adapter a `type` names.
- `starpulse.harnesses`: loading the harness file, the tiers and efforts an agent profile names.
- `starpulse.mermaid_import`: drafting a machine definition from a Mermaid state diagram.
- `starpulse.otlp`: decoding Claude Code's OpenTelemetry log export.

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

StarPulse is versioned `0.y.z` until its interfaces settle: a minor version can break the config file, the adapter
contract or the command line, and a patch release never does. Each release is a
[GitHub Release](https://github.com/trantor-org/starpulse/releases) whose notes list the pull requests it contains.

## Development

```sh
git clone https://github.com/trantor-org/starpulse && cd starpulse
uv sync
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build
uv run starpulse serve
```

`uv run pytest` runs the suite; `pnpm --dir starpulse/web run check` checks the page. See
[Development](https://github.com/trantor-org/starpulse/blob/main/docs/development.md) for the import layers, API type
generation, benchmarks and UI previews.

## Contributing

Open an [issue](https://github.com/trantor-org/starpulse/issues/new/choose) for a bug, a feature or a question.
Pull requests come from collaborators; [CONTRIBUTING.md](CONTRIBUTING.md) has how both work.

## License

MIT; see [LICENSE](LICENSE).
