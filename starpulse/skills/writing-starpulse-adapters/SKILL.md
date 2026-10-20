---
name: writing-starpulse-adapters
description: Connects a tracker, a harness, a scheduler or an analysis engine to StarPulse by writing an adapter against its board, machine-events, runs or insights contract, testing it with the adapter kit, and posting machine events and runs to the CloudEvents ingest. Use when asked to show Jira, Linear, GitHub or another tracker's tasks on StarPulse, to push lifecycle events or workflow runs into it, or to test an adapter.
---

# Writing StarPulse Adapters

An adapter produces one of four records. The models are in `starpulse.contracts`, each with a JSON
Schema under `starpulse/schemas/`; an unknown field is an error, so a misspelt one is refused, not
lost.

| Contract | Record | Written to |
|---|---|---|
| `board` | `BoardTask`: `id`, `title`, `team`, `lane`, `dependencies`, `references`, `settled`, `created_at`, `settled_at`, `observed_at`, `profile`, `assignee`, `labels`, `milestone`, `description`, `acceptance_criteria`, `acceptance_checked`, `pause_reason`, `notes`, `moves` | a board adapter's `Board` |
| `machine-events` | `MachineEvent`: `machine`, `event`, exactly one of `task` or `run`, `actor`, `time` (epoch seconds); `source` and `data` come from a producer posting through the ingest (docs/sources.md) | the ingest, `POST /api/machine-events`; an adapter in the server process appends to `machine:events` |
| `runs` | `Dag`: `name`, `status`, `runId`, `startedAt`, `finishedAt`, `steps` | a runs adapter's `RunsSink`, or a Step CloudEvent posted to the ingest |
| `insights` | `Finding`: `id`, `engine` (`name`, `version`), `scope` (any of `team`, `machine`, `state`, `task`), `severity` (`info`, `warn`, `act`), `text` (at most 280 characters), `evidence` (each a labelled `url` or `query`), `created_at`, `expires_at` | a hub's `POST /api/insights` under the engine token; `DELETE /api/insights/<id>` retracts |

Pick the contract first: a tracker is a board, a hook that says a task moved is machine events, a
scheduler is runs, an engine that reads the history and reports on it is insights. A finding is
about a team, machine, state or task, never a person: the contract has no field for one, and a
scope that names a person is refused.

## Write a board adapter

1. Make a module with `board(settings, base)` returning `starpulse.board.Board`: `settings` is the
   rest of the `[board]` table, `base` the config file's directory.
2. Give it `machines` (the machines the page draws, the Board's as `board`), `start` (feeds each
   task as it changes) and `keys`, a `TaskKeys(key=<whole-key pattern>, branch=<pattern whose
   group 1 is the key>, key_format=...)`.
3. Set each task's `lane` to a state id of the Board machine: the status lower-cased, spaces as `_`.
4. Add `writer(task, status, actor)` so the page and the agent can move tasks: it returns a
   `Written`, whose refusal `output` and `skill` are what `starpulse task move` reports. An actor
   outside a move's `writers` is refused before the writer is called. `assign`, `read`, `edit` and
   `archive` are optional.
5. Name the module in `[board] type`: a built-in name or a dotted path an installed package
   provides. `starpulse._internal.board.upstream_backlog` is the reference adapter;
   `starpulse._internal.board.jira` imports its machine from the tracker's own workflow. Author the
   machine's states and writers with the `authoring-starpulse-machines` skill.

Done when `starpulse doctor` reports `adapter:board` ok.

## Test an adapter with the kit

1. Subclass the kit for the contract, from `starpulse.adapter_kit`: `BoardAdapterKit`,
   `MachineEventsAdapterKit`, `RunsAdapterKit` or `InsightsEngineKit`. An insights engine declares
   only `produce()`; the kit posts, re-posts and retracts each finding through a served hub and
   checks the stream sends every state.
2. Otherwise declare `keys = TaskKeys(...)` and
   `branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}`, one branch that names a task and
   one that names none. A board or machine-events kit also declares `machines`; a board kit declares
   `teams = {"PROJ-1": "PROJ"}`, the team key the adapter derives for each task, and sets `writer`
   when it has one.
3. Override `produce()` to return the records the adapter writes, as plain dicts shaped as the
   schema. A runs adapter that reports concurrency pools also overrides `produce_pools()`; each
   `Dag.pool` must name one of them.
4. Run `pytest`: the kit checks each record against the contract, keys, branches and declared
   team, and that StarPulse places it.

Done when every kit check passes against records the adapter actually produced.

## Post machine events and runs to the ingest

The ingest, `POST /api/machine-events`, is the one write path for machine events and runs from a
cron line, a systemd unit, a CI job or a scheduler hook; it needs no Redis and no database access.
Declare the producer in the server's config with its token in the environment (docs/serving.md):

```toml
[[producers]]
name = "ci-bot"              # the CloudEvents `source`
token_env = "CI_BOT_TOKEN"   # the variable holding its bearer token
machines = ["delivery"]      # the machines it may write; a run-only producer leaves out `machines` and `actors`
actors = ["ci"]
```

Post one CloudEvent as `Content-Type: application/cloudevents+json`, or a JSON list as
`application/cloudevents-batch+json`, with `Authorization: Bearer $CI_BOT_TOKEN`.

- A machine event carries `machine`, `type` (the event), `actor` and exactly one of `subject` (the
  task) or `run`.
- A run is a Step event: `type` `StepStarted` or `StepFinished`, `subject` the run's id, `data`
  holding `workflow`, `status` (`not_started`, `queued`, `running`, `succeeded`, `failed`,
  `aborted` or `skipped`) and, for a step's entry, `step` with `depends` naming the steps it waits
  on. The run is drawn as `pushed/<source>/<workflow>`.

```sh
curl -fsS -X POST "$STARPULSE_URL/api/machine-events" -H "Authorization: Bearer $CI_BOT_TOKEN" \
  -H 'Content-Type: application/cloudevents+json' \
  -d '{"specversion":"1.0","id":"r1-start","source":"ci-bot","type":"StepStarted","subject":"r1",
       "data":{"workflow":"nightly","status":"running"}}'
```

201 means the entry is in the event log; a repeated `id` from one source is written once. 4xx means
refused and nothing written: 401 a missing or wrong token, 403 another producer's `source`, machine
or actor, 400 a malformed event or one its machine does not declare, 413 an oversize body. 503
means the database is unreachable, so retry. A missing entry never means the run failed.

A scheduler worth a full adapter is a `[[runs]]` instance (`name`, `type`, `url`) whose module
offers `start(url)` and `follow(url, runs, log)`, publishing `Dag`s through
`RunsSink.set_dags(dags, error, pools, startable)`: a `Dag` lists its running and queued runs in
`active`; `pools` is the list of concurrency pools, empty when the scheduler has none; `startable`
names the workflows `start` can run when it cannot start all of them (those a GitHub workflow file
marks `workflow_dispatch`). Its workflows are drawn as `<name>/<workflow>`.

## Check it

Run `starpulse config check` for the effective config and `starpulse doctor` for each adapter,
reading each failing check's `reason`. Done when `ok` is true for both.
