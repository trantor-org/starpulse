# StarPulse

<p align="center">
  <a href="https://github.com/trantor-org/starpulse/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/trantor-org/starpulse/ci.yml?branch=main&style=flat-square&label=ci" alt="CI status"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/v/starpulse?style=flat-square&label=pypi" alt="PyPI version"></a>
  <a href="https://pypi.org/project/starpulse/"><img src="https://img.shields.io/pypi/pyversions/starpulse?style=flat-square" alt="Python version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License: MIT"></a>
</p>

**See the flow of work on one page:** your tasks, your scheduler's runs, and the agents and people moving them, live.

**[Try the live demo →](https://trantor-org.github.io/starpulse-demo/main/flow-view.html)** (runs in your browser, no server)

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and Python 3.14+.

```sh
uvx starpulse serve
```

Open <http://localhost:8766>.

## What it shows

- **Tasks** moving through their lifecycle, from its own Markdown board, [Backlog.md](https://github.com/MrLesk/Backlog.md) or Jira.
- **Workflow runs** from [Dagu](https://github.com/dagu-org/dagu), GitHub Actions, systemd timers or anything that calls `starpulse emit`.
- **Agents and pull requests**: Claude Code sessions, Copilot and pull requests on their way to merge.
- **A hub** that joins many instances behind single sign-on.

## Learn more

[Configure](https://github.com/trantor-org/starpulse/blob/main/docs/serving.md) ·
[Sources](https://github.com/trantor-org/starpulse/blob/main/docs/sources.md) ·
[Agent CLI](https://github.com/trantor-org/starpulse/blob/main/docs/cli.md) ·
[Hub](https://github.com/trantor-org/starpulse/blob/main/docs/hub.md) ·
[Adapters](https://github.com/trantor-org/starpulse/blob/main/docs/adapters.md) ·
[Security](https://github.com/trantor-org/starpulse/blob/main/docs/security.md) ·
[Compatibility](https://github.com/trantor-org/starpulse/blob/main/docs/public-surface.md) ·
[Contributing](CONTRIBUTING.md)

MIT licensed.
