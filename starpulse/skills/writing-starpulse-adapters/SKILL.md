---
name: writing-starpulse-adapters
description: Connects a tracker, a harness, a scheduler or an analysis engine to StarPulse by writing an adapter against its board, machine-events, runs or insights contract, testing it with the adapter kit, and reporting runs with `starpulse emit`. Use when asked to show Jira, Linear, GitHub or another tracker's tasks on StarPulse, to push lifecycle events or workflow runs into it, or to test an adapter.
---

# Writing StarPulse Adapters

An adapter produces one of four records for StarPulse. The models are in `starpulse.contracts`, and each has a JSON
Schema under `starpulse/schemas/`. Unknown fields are an error, so a misspelt one is refused rather than lost.

| Contract | Record | Written to |
|---|---|---|
| `board` | `BoardTask`: `id`, `title`, `team`, `lane`, `dependencies`, `references`, `settled`, `created_at`, `settled_at`, `observed_at`, `assignee`, `holder`, `labels`, `milestone`, `description`, `moves` | a board adapter's `Board` |
| `machine-events` | `MachineEvent`: `machine`, `event`, exactly one of `task` or `run`, `actor`, `time` (epoch seconds) | the database event log under `machine:events` |
| `runs` | `Dag`: `name`, `status`, `runId`, `startedAt`, `finishedAt`, `steps` | a runs adapter's `RunsSink`, or `starpulse emit` |
| `insights` | `Finding`: `id`, `engine` (`name`, `version`), `scope` (any of `team`, `machine`, `state`, `task`), `severity` (`info`, `warn`, `act`), `text` (at most 280 characters), `evidence` (each a labelled `url` or `query`), `created_at`, `expires_at` | a hub's `POST /api/insights` under the engine token; `DELETE /api/insights/<id>` retracts |

Pick the contract first: a tracker is a board, a hook that says a task moved is machine events, a scheduler is runs, an engine that reads the history and reports what it found is insights. A finding is about a team, machine, state or task, never a person: the contract has no field for one, and a scope that names a person is refused.

## Write a board adapter

1. Make a module with `board(settings, base)` returning `starpulse.board.Board`: `settings` is the rest of the
   `[board]` table and `base` the config file's directory.
2. Give it `machines` (the machines the page draws, the Board's as `board`), `start` (feeds each task as it changes)
   and `keys`, a `TaskKeys(key=<whole-key pattern>, branch=<pattern whose group 1 is the key>, key_format=...)`.
3. A task's `lane` is a state id of the Board machine: the status lower-cased with spaces as `_`.
4. Add a `writer(task, status, actor)` to let the page and the agent move tasks: it returns a `Written`, and its
   refusal's `output` and `skill` are what `starpulse task move` reports. An actor outside a move's `writers` is refused
   before the writer is called. `assign`, `read`, `edit`, `archive` and `history` are optional.
5. Name the module in `[board] type`, a module under `starpulse` or a dotted path an installed package provides.
   `starpulse._internal.adapters.boards.upstream_backlog` is the reference adapter, and `starpulse._internal.adapters.boards.jira` one that imports its machine from the
   tracker's own workflow. The machine's states and writers are authored with the
   `authoring-starpulse-machines` skill.

Done when `starpulse doctor` reports `adapter:board` as ok.

## Test an adapter with the kit

1. Subclass the kit for the contract: `BoardAdapterKit`, `MachineEventsAdapterKit`, `RunsAdapterKit` or
   `InsightsEngineKit`, from `starpulse.adapter_kit`. An insights engine declares only `produce()`, its findings as plain
   dicts; the kit posts, re-posts and retracts each through a served hub and checks the stream sends every state.
2. Unless it is an insights engine, declare `keys = TaskKeys(...)` and `branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}`, with a branch that
   names a task and one that names none. A board or machine-events kit also declares `machines`; a board kit declares
   `teams = {"PROJ-1": "PROJ"}`, the team key your adapter derives for each task it produces, and one with a writer
   sets `writer`.
3. Override `produce()` to return the records your adapter writes, as plain dicts shaped as the schema. A runs adapter
   that reports concurrency pools also overrides `produce_pools()`; each `Dag.pool` must name one of them.
4. Run `pytest`. The kit checks each record against the contract, its keys and branches, that a board task is in the team you declared
   for it, and that StarPulse places it.

Done when every kit check passes against records your adapter actually produced.

## Report runs from any scheduler

Call `starpulse emit start|end --workflow W --run ID --status S` from a cron line, a systemd unit or a scheduler hook,
at each start and end. Add `--step NAME` for a step's entry, with `--depends a,b` naming the steps it waits on. Status is
`not_started`, `queued`, `running`, `succeeded`, `failed`, `aborted` or `skipped`. The command finds the database event
log from `--config` or the default `starpulse.toml`, like `starpulse serve`. Exit 1 means the event log refused the entry,
usually because its database is unreachable; exit 2 means a flag or configuration value is invalid. A missing entry
never means the run failed.

A scheduler worth a full adapter is a `[[runs]]` instance (`name`, `type`, `url`) whose module offers `start(url)` and
`follow(url, runs, group)`, publishing `Dag`s through `RunsSink.set_dags(dags, error, pools, startable)` (a `Dag` lists its running and queued runs in `active`,
`pools` is the list of concurrency pools, empty when the scheduler has none, and `startable` names the workflows
`start` can run when it cannot start all of them, such as those a GitHub workflow file marks `workflow_dispatch`);
its workflows are drawn as `<name>/<workflow>`.

## Check it

Run `starpulse config check` for the effective config and `starpulse doctor` for each adapter, reading each failing
check's `reason`. Done when `ok` is true for both.
