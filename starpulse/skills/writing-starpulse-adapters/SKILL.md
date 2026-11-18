---
name: writing-starpulse-adapters
description: Connects a tracker, a harness or a scheduler to StarPulse by writing an adapter against its machine-events or runs contract, testing it with the adapter kit, and posting machine events and runs to the CloudEvents ingest. Use when asked to push lifecycle events or workflow runs from a harness, a hook or a scheduler into StarPulse, or to test an adapter. StarPulse serves its own Markdown board and offers no board contract, so a Linear or GitHub tracker is not an adapter.
---

# Writing StarPulse Adapters

An adapter produces one of two records for StarPulse. The models are in `starpulse.contracts`, and each has a JSON
Schema under `starpulse/schemas/`. Unknown fields are an error, so a misspelt one is refused rather than lost.

| Contract | Record | Written to |
|---|---|---|
| `machine-events` | `MachineEvent`: `machine`, `event`, exactly one of `task` or `run`, `actor`, `time` (epoch seconds), optionally `source` and `data` (set by a producer posting through `POST /api/machine-events`, see docs/sources.md) | the CloudEvents ingest, `POST /api/machine-events`; an adapter in the server process appends to `machine:events` |
| `runs` | `Dag`: `name`, `status`, `runId`, `startedAt`, `finishedAt`, `steps` | a runs adapter's `RunsSink`, or a Step CloudEvent posted to the ingest |

Pick the contract first: a hook that says a task moved is machine events, a scheduler is runs. The board is not a
contract: StarPulse serves its native Markdown board directly, and pluggable boards are withdrawn until a second tracker is
planned (ADR: Pluggable boards are withdrawn).

## Test an adapter with the kit

1. Subclass the kit for the contract: `MachineEventsAdapterKit` or `RunsAdapterKit`, from
   `starpulse.runtime.adapter_kit`.
2. Declare `keys = TaskKeys(...)` and `branches = {"feature/PROJ-1-add-x": "PROJ-1", "main": None}`, with a branch that
   names a task and one that names none. A machine-events kit also declares `machines`.
3. Override `produce()` to return the records your adapter writes, as plain dicts shaped as the schema. A runs adapter
   that reports concurrency pools also overrides `produce_pools()`; each `Dag.pool` must name one of them.
4. Run `pytest`. The kit checks each record against the contract, its keys and branches, and that StarPulse places it.

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
A producer that speaks Connect or gRPC calls `starpulse.v1.CloudEventsIngest` `Publish` or `PublishBatch` on the same port, the token in `authorization` metadata and the event as `io.cloudevents.v1.CloudEvent` (docs/sources.md, Over Connect).

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
`follow(url, runs, group)`, publishing `Dag`s through `RunsSink.set_dags(dags, error, pools, startable, cpu)` (a `Dag` lists its running and queued runs in `active`,
`pools` is the list of concurrency pools, empty when the scheduler has none, and `startable` names the workflows
`start` can run when it cannot start all of them, such as those a GitHub workflow file marks `workflow_dispatch`, and `cpu` is
`{"share": 0..1, "cores": N}`, the share of all the host's cores the scheduler's units used since the last reading, or `None`);
its workflows are drawn as `<name>/<workflow>`. A `Dag` also carries its `schedule` (cron expressions, empty when it is
started by hand) and `stats` (`runs`, `hours`, `medianSeconds`, `p95Seconds`, `failureShare` over the last seven days;
`None` when the workflow never ran, never zeros), `rerun` (`key`, `repeats`, `step`: what the workflow declares about a rerun
repeating its effects; `None` when it declares nothing), and each `Step` its `precondition`, its `lock` and its `last` outcomes
(up to five, newest first). The fields are required but nullable, so an adapter that has no value sends `None`, and the
adapter kit fails one that leaves a field out.

## Check it

Run `starpulse config check` for the effective config and `starpulse doctor` for each adapter, reading each failing
check's `reason`. Done when `ok` is true for both.
