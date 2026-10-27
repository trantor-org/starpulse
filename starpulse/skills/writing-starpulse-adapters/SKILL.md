---
name: writing-starpulse-adapters
description: Connects a tracker, a harness or a scheduler to StarPulse by writing an adapter against its board, machine-events or runs contract, testing it with the adapter kit, and posting machine events and runs to the CloudEvents ingest. Use when asked to show Jira, Linear, GitHub or another tracker's tasks on StarPulse, to push lifecycle events or workflow runs into it, or to test an adapter.
---

# Writing StarPulse Adapters

An adapter produces one of four records for StarPulse. The models are in `starpulse.contracts`, and each has a JSON
Schema under `starpulse/schemas/`. Unknown fields are an error, so a misspelt one is refused rather than lost.

| Contract | Record | Written to |
|---|---|---|
| `board` | `BoardTask`: `id`, `title`, `team`, `lane`, `dependencies`, `references`, `settled`, `created_at`, `settled_at`, `observed_at`, `profile`, `assignee`, `labels`, `milestone`, `description`, `acceptance_criteria`, `acceptance_checked`, `pause_reason`, `notes`, `moves` | a board adapter's `Board` |
| `machine-events` | `MachineEvent`: `machine`, `event`, exactly one of `task` or `run`, `actor`, `time` (epoch seconds), optionally `source` and `data` (set by a producer posting through `POST /api/machine-events`, see docs/sources.md) | the CloudEvents ingest, `POST /api/machine-events`; an adapter in the server process appends to `machine:events` |
| `runs` | `Dag`: `name`, `status`, `runId`, `startedAt`, `finishedAt`, `steps` | a runs adapter's `RunsSink`, or a Step CloudEvent posted to the ingest |

Pick the contract first: a tracker is a board, a hook that says a task moved is machine events, a scheduler is runs.

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
   `starpulse.board.adapters.upstream_backlog` is the reference adapter, and `starpulse.board.adapters.jira` one that imports its machine from the
   tracker's own workflow. The machine's states and writers are authored with the
   `authoring-starpulse-machines` skill.

Done when `starpulse doctor` reports `adapter:board` as ok.

## Test an adapter with the kit

1. Subclass the kit for the contract: `BoardAdapterKit`, `MachineEventsAdapterKit` or
   `RunsAdapterKit`, from `starpulse.runtime.adapter_kit`.
2. Declare `keys = TaskKeys(...)` and `branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}`, with a branch that
   names a task and one that names none. A board or machine-events kit also declares `machines`; a board kit declares
   `teams = {"PROJ-1": "PROJ"}`, the team key your adapter derives for each task it produces, and one with a writer
   sets `writer`.
3. Override `produce()` to return the records your adapter writes, as plain dicts shaped as the schema. A runs adapter
   that reports concurrency pools also overrides `produce_pools()`; each `Dag.pool` must name one of them.
4. Run `pytest`. The kit checks each record against the contract, its keys and branches, that a board task is in the team you declared
   for it, and that StarPulse places it.

Done when every kit check passes against records your adapter actually produced.

## Post machine events and runs to the ingest

The ingest, `POST /api/machine-events`, is the one write path for machine events and for runs, from a cron line, a systemd
unit, a CI job or a scheduler hook. It needs no Redis and no access to the database. Declare the producer in the server's
config, with its token in the environment (docs/serving.md):

```toml
[[producers]]
name = "ci-bot"              # the CloudEvents `source`
token_env = "CI_BOT_TOKEN"   # the variable holding its bearer token
machines = ["delivery"]      # the machines it may write; a run-only producer leaves out `machines` and `actors`
actors = ["ci"]
```

Post one CloudEvent, `Content-Type: application/cloudevents+json`, or a JSON list as `application/cloudevents-batch+json`,
with `Authorization: Bearer $CI_BOT_TOKEN`. A machine event carries `machine`, `type` (the event), `actor` and exactly one
of `subject` (the task) or `run`. A run is a Step event: `type` `StepStarted` or `StepFinished`, `subject` the run's id,
and `data` holding `workflow`, `status` (`not_started`, `queued`, `running`, `succeeded`, `failed`, `aborted` or `skipped`),
and for a step's entry `step` with `depends` naming the steps it waits on. The run is drawn as `pushed/<source>/<workflow>`.
A producer that speaks gRPC calls `starpulse.v1.CloudEventsIngest` `Publish` or `PublishBatch` on the same port, the token in `authorization` metadata and the event as `io.cloudevents.v1.CloudEvent` (docs/sources.md, Over gRPC).

```sh
curl -fsS -X POST "$STARPULSE_URL/api/machine-events" -H "Authorization: Bearer $CI_BOT_TOKEN" \
  -H 'Content-Type: application/cloudevents+json' \
  -d '{"specversion":"1.0","id":"r1-start","source":"ci-bot","type":"StepStarted","subject":"r1",
       "data":{"workflow":"nightly","status":"running"}}'
```

201 means the entry is in the event log; a repeated `id` from one source is written once. 4xx means the event was
refused and nothing was written: 401 for a missing or wrong token, 403 for another producer's `source`, machine or actor,
400 for an event its machine does not declare or a malformed one, 413 for an oversize body. 503 means the database is
unreachable, so retry. A missing entry never means the run failed.

A scheduler worth a full adapter is a `[[runs]]` instance (`name`, `type`, `url`) whose module offers `start(url)` and
`follow(url, runs, group)`, publishing `Dag`s through `RunsSink.set_dags(dags, error, pools, startable)` (a `Dag` lists its running and queued runs in `active`,
`pools` is the list of concurrency pools, empty when the scheduler has none, and `startable` names the workflows
`start` can run when it cannot start all of them, such as those a GitHub workflow file marks `workflow_dispatch`);
its workflows are drawn as `<name>/<workflow>`. A `Dag` also carries its `schedule` (cron expressions, empty when it is
started by hand) and `stats` (`runs`, `hours`, `medianSeconds`, `p95Seconds`, `failureShare` over the last seven days;
`None` when the workflow never ran, never zeros), and each `Step` its `precondition`, its `lock` and its `last` outcomes
(up to five, newest first). The fields are required but nullable, so an adapter that has no value sends `None`, and the
adapter kit fails one that leaves a field out.

## Check it

Run `starpulse config check` for the effective config and `starpulse doctor` for each adapter, reading each failing
check's `reason`. Done when `ok` is true for both.
