<p align="center">
  <a href="https://trantor-org.github.io/starpulse-demo/main/flow-view.html"><img src="https://trantor-org.github.io/starpulse-demo/main/flow-view-star-map.png" alt="StarPulse's star map: tasks, workflow runs and agents moving live" width="900"></a>
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
  <a href="https://trantor-org.github.io/starpulse-demo/main/flow-view.html">Live demo</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/serving.md">Configure</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/sources.md">Sources</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/cli.md">Agent CLI</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/hub.md">Hub</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/adapters.md">Adapters</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/security.md">Security</a> ·
  <a href="https://github.com/trantor-org/starpulse/blob/main/docs/public-surface.md">Compatibility</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

## Quick start

```sh
uvx starpulse serve   # then open http://localhost:8766
```

## Views

| Kanban | Orbit | Workflow runs |
|---|---|---|
| <img src="https://trantor-org.github.io/starpulse-demo/main/flow-view-kanban.png" alt="Kanban view"> | <img src="https://trantor-org.github.io/starpulse-demo/main/flow-view-orbit.png" alt="Orbit view"> | <img src="https://trantor-org.github.io/starpulse-demo/main/flow-view-dags.png" alt="Workflow runs view"> |

Reads tasks from its own Markdown board, Backlog.md or Jira; runs from Dagu, GitHub Actions or systemd; agents from Claude Code and Copilot.

MIT licensed.
