# Run a hub

`starpulse serve --hub` serves the same package from a Postgres history, for a hub that instances forward to.
Install the hub extras (`uvx --from 'starpulse[hub]' starpulse serve --hub`) and set `database_url` to a Postgres
database in the config; a config with none, or with a SQLite URL, is refused before anything starts. The hub brings
the database's schema to the latest revision on every start: the history tables are versioned with the package by
Alembic (`starpulse/_internal/eventlog/migrations`, revisions recorded in `starpulse_alembic_version`), so upgrading the package and
restarting upgrades the schema. An instance without `--hub` keeps its SQLite file and never imports the hub extras.

A hub also requires an `[oidc]` table, because viewers sign in with the hub's OpenID Connect issuer before anything is
drawn; a hub without one is refused before it starts, and an instance without `--hub` refuses the table rather than
serve ungated. The hub is a confidential client of the issuer (authorization-code flow with PKCE, a state and a nonce;
ID tokens must verify against the issuer's published keys):

```toml
[oidc]
issuer = "https://id.example.com/realms/flow"          # its /.well-known/openid-configuration names the endpoints
client_id = "starpulse-hub"
client_secret_env = "STARPULSE_OIDC_SECRET"            # the environment variable holding the client secret
redirect_uri = "https://hub.example.com/auth/callback" # registered at the issuer; its /auth/callback path is fixed
allowed_groups = ["flow-viewers"]                      # an account holding none of these is refused with the reason
groups_claim = "groups"                                # optional: the ID token claim that lists an account's groups
scopes = ["openid", "profile", "email"]                # optional: add the scope your issuer needs for the groups claim
engine_token_env = "STARPULSE_ENGINE_TOKEN"            # optional: the token of an insights engine, never a viewer's
reader_token_env = "STARPULSE_TOKEN"                   # optional: an agent's read-only token; it reads, never writes
```

Before sign-in every path but `/auth/login` and `/auth/callback` answers 401, including the page, `/api/events` and every
write. Sign-in sets an `HttpOnly` session cookie that lasts eight hours; sessions live in the hub's memory, so a restart
signs everyone out. The credentials are separate: a per-instance token passes only on `POST /api/runs/events` and `POST /api/forward`, the
engine token only on the engine's routes, and neither signs a viewer in. The reader token is for an agent that reads
the hub without a browser: a `GET` or `HEAD` of a viewer route with `Authorization: Bearer <reader token>` is served as
a signed-in viewer's would be, and the same token on any write, instance or engine route answers 401. Set the same
value as `STARPULSE_TOKEN` where the agent CLI runs, and its verbs read the hub. The hub refuses to start when any two
of the instance, engine and reader tokens are equal. A new route of the server is a viewer route
until the gate says otherwise. The test suite signs in against a
[mock OIDC server](https://github.com/navikt/mock-oauth2-server) container, so it needs Docker or Podman for those cases.

### Retention and rollups

A hub keeps its raw events (`starpulse_events`) in one partition per UTC day, keyed on the event's `at` time, and
drops whole days instead of deleting rows, so it starts no row prune and writes no event log archive. An instance on
SQLite is unchanged: it keeps one table and prunes by deleting rows, archiving each first.

```toml
hub_retention_days = 14   # the default; a whole number of days, 1 or more
```

- **Partitions.** The hub creates today's and tomorrow's partition before it serves and again every hour, so an
  insert at midnight finds its partition already there. An event whose `at` falls on a day with no partition is refused
  by the database, so a forwarder must create that day's partition (`starpulse._internal.hub.hub.ensure_partitions`) or refuse
  events older than the retention bound.
- **Retention.** A day more than `hub_retention_days` before today is rolled up and then dropped (`DROP TABLE`,
  never `DELETE`), in one transaction, so a partition is never dropped without its rollup. A reader whose cursor sat
  in a dropped day finds the oldest retained event past its cursor on its next poll and records the span in
  `starpulse_gaps`.
- **Rollups.** `starpulse_day_rollups` holds one row per UTC day, team, machine and state: `entries`, how many tasks
  or runs entered the state that day; `open_entries`, how many of those had not left it when the day was rolled up;
  and `seconds`, how long the others stayed, from entering the state to the next event that moved the task or run out
  of it (which may be on a later day). The team is the entering event's `team` field, and `""` when the event names
  none. Trends older than retention read this table; anything that needs individual events is limited to the
  retained days.

## Post findings from an engine

A hub with `engine_token_env` set takes findings from an external engine: a separate package that reads the hub's
history and says what it found. This package holds no engine code; the insights API is the fourth contract beside the
board, machine-event and runs records, and its record is `Finding` (`starpulse/schemas/insights.schema.json`):

```sh
curl -X POST https://hub.example.com/api/insights -H "Authorization: Bearer $STARPULSE_ENGINE_TOKEN" -d '{
  "id": "slow-review",
  "engine": {"name": "skill-coach", "version": "1.4.0"},
  "scope": {"team": "platform", "state": "review"},
  "severity": "warn",
  "text": "Review takes four times as long as the norm.",
  "evidence": [{"label": "time in review", "url": "https://hub.example.com/history?state=review"}],
  "created_at": 1700000000
}'
curl -X DELETE https://hub.example.com/api/insights/slow-review -H "Authorization: Bearer $STARPULSE_ENGINE_TOKEN"
```

- **Fields.** `id` names the finding, `engine` the `name` and `version` that made it, `severity` is `info`, `warn` or
  `act`, `text` is at most 280 characters, and `created_at` and the optional `expires_at` are epoch seconds. `evidence`
  lists labelled links, each exactly one of a `url` or a history `query`. `scope` may name a `team`, `machine`, `state`
  and `task`, all optional. The contract has no field for a person, and a body with an unknown field, a scope that
  names an assignee or a user included, is refused: a finding is about work, never about someone.
- **Answers.** A new id answers 201 `{id, replaced: false}`. A re-post of an id replaces its finding and answers 200
  `{id, replaced: true}`. A body the contract refuses answers 400 naming the field to fix, one over 64 KiB 413, and a
  history store that refuses the write 503; none of them writes or sends anything. `DELETE /api/insights/<id>` retracts
  a finding (200 `{id, retracted: true}`), and an id that is unknown or already retracted answers 404.
- **Credentials.** Only the engine token reaches these routes, and no viewer's session or forwarder's token does. A hub
  without `engine_token_env`, and an instance without `--hub`, has no insights routes and answers 404.
- **History and stream.** Findings are kept in `starpulse_insights`, a retracted one with its `retracted_at`. The
  stream sends an `insight` event `{id, finding}` for each post and re-post and `{id, finding: null}` for a retraction,
  and the snapshot's `insights` lists the findings neither retracted nor past their `expires_at`, so a client that
  connects later reads them, as does a hub that restarts. The page draws none of them.

An engine author tests against the real routes with `InsightsEngineKit` from `starpulse.adapter_kit`: override
`produce()` to return the engine's findings as plain dicts, and the kit checks each against the contract and schema,
posts, re-posts and retracts each through a served stack and asserts the stream sends every state, and asserts a
finding scoped to a person is refused.

## Configure a level

A hub draws one level above the Board: a flow graph over the trajectories of one Board machine, merged across
sources. It is configuration, not an org chart; the package has no pod, department or org. A `[level]` table names
what the level reads and how it is judged. An IC instance parses and checks the table but draws no level.

```toml
[level]
machine = "board"        # the Board machine whose trajectories the level reads
goal = "done"            # the terminal state the level is judged by
gates = ["review"]       # policy states every run should cross
terminals = [            # every way a run ends
  { id = "done", role = "goal" },
  { id = "archived", role = "abandoned" },
]
facets = [{ id = "source" }, { id = "type", label = "work type" }, { id = "repo" }]
title = "Flow graph"     # what the page calls the level
subject = "task"         # what one trajectory is
runs = "agent sessions"  # what is attached to a trajectory
series = "delivery"      # the card series the level opens

[level.orbit]
suns = "working"                                   # "terminal" (default) or "working"
working = ["ready", "in_progress", "review"]       # the working states drawn as suns when suns = "working"

[level.activity]
measure = "share"   # "share" (default), "count" or "flux"
pace = "min"        # "live", "min" (default, one day per minute) or "fast" (one day per ten seconds)
```

| Field | Required | Meaning |
|---|---|---|
| `machine` | yes | The Board machine the level reads. |
| `goal` | yes | The state the level is judged by; one of `terminals`. |
| `terminals` | yes | Every way a run ends, each `{ id, role }`. The role is `goal`, `abandoned` or another outcome to watch; each id is listed once. |
| `gates` | no | Policy states every run should cross. Default: none. |
| `orbit.suns` | no | What the orbit view circles: `terminal` states, or the `working` states of `orbit.working`. Default `terminal`. |
| `orbit.working` | with `suns = "working"` | The working states drawn as suns. None may be a terminal. |
| `facets` | no | The fields a viewer groups and filters by, each `{ id, label }`; the label defaults to the id. |
| `activity.measure` | no | How activity becomes dots: `share`, `count` or `flux`. Default `share`. |
| `activity.pace` | no | How fast the page replays it: `live`, `min` or `fast`. Default `min`. |
| `title` | no | The level's name on the page. Default `Flow graph`. |
| `subject` | no | What one trajectory is called. Default `task`. |
| `runs` | no | What is attached to a trajectory. Default `runs`. |
| `series` | no | The card series the level opens. Default none. |

A level that cannot be read is refused when the config loads, naming the key. Every state it names (`goal`, `gates`,
`terminals`, `orbit.working`) must be a state of `machine`: when the board is assembled, a level that names a state
its machine lacks, or a machine the board does not draw, is refused, naming it, before anything is served.

A viewer's facet filter keeps a run only when the run has a value for each selected facet and that value is selected.
A run without a value for a selected facet is excluded, never counted as zero or as an empty value; selecting nothing
keeps every run.

## Read the level on the page

A hub with a `[level]` table adds a **Flow graph** view to the page (`?view=graph`), the level above the Board, drawn from
`GET /api/level` alone: it reads only the `level` echo above, never a name from the page's own build. Each source is a
planet on a closed orbit; the orbit has one petal per sun, and the planet spends a share of each period in a petal
that grows with the source's share of that sun (never zero, so the planet's speed at the centre crossing differs
between petals by under four times). A sun is a terminal state sized by the runs that ended there, or with
`orbit.suns = "working"` a working state sized by the task-days spent there, the terminals standing in a column to its
right. At rest the view names each body and moves only the planets, each with a short tail, and the comets: a comet falls
into a terminal for each batch of arrivals (`activity.measure`: `share` and `flux` batch by a tenth of the source's WIP,
`count` by five), replayed at `activity.pace`: `live` follows real time with no loop, `min` replays a day a minute and
`fast` a day in ten seconds, both looping the window. The numbers are on demand: hovering a source rings it with where
its runs end and traces it to each sun, hovering a sun traces each source to it, and either opens a tip with the shares,
counts and the source's bottleneck state. A click focuses a body and Tab steps through them, the sources and then the
suns, leaving the card past the last: a steady ring follows the focused body while the replay keeps it moving, its
traces stay lit, and a details panel docks at the card's right edge (`src/features/orbit/orbitDetails.ts`). For a source it gives the
open and ended runs, each terminal's count and share, and the drift, then the time in each state (share, stays, mean
stay), the open runs oldest first with those past `aging.threshold_s` flagged, and the latest arrivals. For a terminal
sun it gives the runs that ended there, their share of every end and the last day's count, then each source's count and
the latest arrivals; for a working sun, the open runs, task-days and stays, then each source's time there and the open
runs in that state. A list shows five rows and counts the rest. The panel's close button, Esc or a click on empty space
clears the focus. A second click or Enter on the focused body is held for drilling into it, which waits until a user
can be selected, so it changes nothing yet (`src/features/orbit/orbitFocus.ts`).

The view always shows one of these states:

| State | When | What it draws |
|---|---|---|
| Orbit | `/api/level` answers 200 | The orbit, and under its title a *Source drift* badge when a source reports states the config lacks or omits (the optional `drift: {added, removed}` of a source) |
| Loading | the first answer is pending | A note |
| No level | the server answers 404 or 501 | A note: this server has no level |
| Sign-in | 401, or 403 from the OIDC gate | A card linking `/auth/login` (*Your session ended*, or *This account can't read the level* with *Sign in as someone else*) |
| Error | any other failure, such as a window past the history | The message and **Retry** |

The page asks again every minute. A self-contained demo page (`starpulse demo`) answers `/api/level` itself, with
synthetic sources, and its address picks the state: `?view=graph`, `&suns=working`, `&gate=expired` or
`&gate=refused`, `&pace=fast|live`, `&measure=count`. Motion off in the page's preferences draws one still frame.

The right rail keeps one order in every view: the recent moves at the top and the legend at the bottom, each line
wrapped whole rather than cut to an ellipsis. Nothing on the page scrolls sideways, and every box that scrolls does so vertically with the Kanban columns' thin scrollbar, from one
shared rule at the end of `starpulse/web/src/style.css` that `src/shared/scroll.test.ts` holds to. A Kanban column keeps its scrollbar's
gutter even when it does not overflow, so a stack unfolding past its foot does not narrow its cards, and while a column
scrolls, and until the frame after it has rested 300 ms, its cards take no pointer: one passing under a resting pointer lights no chain, reads no record and draws no modal ahead. The navigator search's Matches keep their gutter the same way and stand aside while they scroll (`useScrollRest` in
`src/shared/scrollRest.ts`, shared with the columns): a match passing under a resting pointer lights nothing on the canvas.

## Forward an instance's events to a hub

An instance sends its machine and runs events to a hub over HTTPS, a batch at a time, in log order. Each side is
config; neither needs the hub extras on the instance.

On the hub, one `[[sources]]` table per instance names the variable that holds that instance's token. Setting the
variable is the grant and removing the table (then restarting `serve`) is the revocation:

```toml
[[sources]]
name = "ana"                 # the instance; the hub stores its events as `<name>/<event_id>`
token_env = "ANA_FORWARD_TOKEN"

aggregates_only = false      # true: refuse any batch that opts in to names
```

On the instance, `[forward]` names the hub and the variable holding the token the hub issued:

```toml
[forward]
url = "https://hub.example.com:8766"
token_env = "HUB_FORWARD_TOKEN"
batch = 50                   # events per request, 1 to 200
```

- **What leaves.** Only the machine and runs streams, cut to the fields their contracts name (`machine`, `event`,
  `task` or `run`, `time`, and a run's `workflow`, `run_id`, `status`, `step`, `depends`). A field a producer added
  stays home.
- **Names stay home by default.** `actor` and `assignee` leave only while the instance is opted in. Run
  `starpulse forward opt-in`, `opt-out` or `status` (`--config` as for `serve`); the flag is
  `starpulse-forward.json` beside the config. The forwarder reads it before every batch, so an opt-out applies at the
  next send with no restart and no call to the hub, even while the hub is unreachable. A batch that failed while
  opted in is rebuilt from the log, so it goes out without names after an opt-out. A hub with `aggregates_only`
  answers an opt-in 403, and the forwarder sends that batch, and the ones after it, without names until the instance
  opts out and in again.
- **The Admin view's Forwarding card** lists what the next batch carries, as the forwarder cuts it, with the hub, when it
  last took a batch, why it did not, and a switch for the opt-in. `GET /api/forwarding` answers that status (`{"configured":
  false}` with no `[forward]` block) and `PUT /api/forwarding` takes `{"opt_in": bool}`, the flag the CLI sets; both answer
  only a loopback or private-network browser, and the page's own origin on a write.
- **Exactly once.** The forwarder reads the instance's event log from a cursor stored in the instance's own database
  (`forward:<url>`), not from a Redis consumer group. The cursor moves only after the hub answers 200, so a batch
  that fails, or a process killed between the send and the answer, is sent again whole; the hub stores each
  `event_id` once and drops the repeat. A new `url` replays the retained log to the new hub.
- **`POST /api/forward`** takes `{"opt_in": bool, "events": [{"event_id", "stream", "fields"}]}` (at most 200 events
  and 1 MiB) as a bearer. A missing or wrong token answers 401, an opt-in to an `aggregates_only` hub 403, a body
  that is no batch 400, and none of them writes anything. An invalid event is counted `rejected` in the 200 so it
  cannot hold the cursor; a 503 means the hub's log refused an event and the batch repeats.
- `[forward]` is for an instance; `serve --hub` refuses it.
