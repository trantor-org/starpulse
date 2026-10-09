# Agent command line

An agent reads and works the board through `starpulse` verbs, each printing one JSON document.

```sh
starpulse board --milestone launch --label api   # tasks per column, with dependencies, pull requests and moves
starpulse task show PROJ-45                      # one task: lane, what it waits on, pull requests, moves
starpulse task moves PROJ-45                     # every column it may move to, allowed or refused to the agent
starpulse task move PROJ-45 review               # move it as the agent; a refusal is the verdict, exit 1
starpulse task trace PROJ-45 --flow in-progress  # where the task has been: Board lanes, or one machine's events
starpulse machine show in-progress               # a machine's states, transitions and the tasks now in each
starpulse milestone list                         # every open milestone: title, outcome, specs and ADRs
starpulse milestone add "Launch" --outcome "Shipped" --spec "doc-1 - plan" --adr docs/adr/a.md
starpulse doc list                               # every open doc: title, type, dates and path, without bodies
starpulse doc create "Plan" --type specification --folder specs --body "# Plan"
starpulse runs list                              # each workflow as <instance>/<workflow> with its latest status
starpulse runs start prod/nightly                # start a run-safe workflow through Run now; its run id
starpulse watch --task PROJ-45                   # one JSON line per change, until you stop it: wait without polling
starpulse analytics health --hours 72            # dwell and WIP per state, throughput and stuck tasks, with gap warnings
starpulse analytics level --hours 48             # the level's WIP, throughput, aging and per-source orbit shares
starpulse analytics trajectories --hours 48      # variants, outliers, expected days and chance of the goal, betweenness
starpulse analytics gates --task PROJ-45         # which gates a run can bypass, with the path that skips each
starpulse analytics forecast --task PROJ-45      # where a run still going is likely to end, and in how many days
starpulse analytics what-if --from review --to in_progress --p 0.1  # the change in the goal and days
starpulse snapshot                               # everything the page draws, as one document
starpulse doctor                                 # does this install work: each check passes or fails, with why
starpulse skills install --claude --codex        # copy the bundled skills into .claude/skills and .agents/skills
starpulse help --agent                           # every verb with its arguments, output keys and exit codes
```

Four verbs work on files, and only `demo` without `--mockup` reads the server; each writes one JSON document the same way:

```sh
starpulse machine validate .starpulse/machines/*.yaml   # schema and compile errors, each with its file and line
starpulse machine import mermaid flow.mmd               # draft a machine file from a stateDiagram-v2 diagram
starpulse config check --config starpulse.toml          # unknown keys by name, and the effective config with defaults
starpulse demo --out demo.html                          # the self-contained demo page (reads the server's snapshot)
```

These verbs read the running server (`starpulse serve`) over HTTP: `--server URL`, else `STARPULSE_URL`, else
`http://localhost:8766`. `STARPULSE_TOKEN`, when set, is sent as a bearer token on every request, so a verb reads a
hub with its reader token (`reader_token_env`) instead of a browser sign-in.
Each writes one JSON document to stdout and nothing to stderr, except `watch`, which writes
one JSON line per change; an error is `{"error": "...", "code": "..."}`. The exit code is 0 for success, 1 for a refused or invalid request, a refused move or a failed `doctor` check, 2 for a usage
error, 3 when the server is unreachable (the error names the address tried) or has no board writer and 4 for something not found. A verb
reads the server on every call and keeps nothing, and `help --agent` is generated from the command parser, so it
lists exactly the verbs there are.

| Verb | Arguments | Document |
|---|---|---|
| `snapshot` | | the server's snapshot: `graphs`, `flows`, `dags`, `pools`, `pulls`, `claims`, `insights`, `settled`, ...; each `flows` entry but the Board's also carries `ties` (`{kind, machine, state, count, dag, when}`: `declared`, `observed` or `dag`), `parent`, `depth`, `chain`, `nested`, `last` and `stuck` (`{machine, state, since}`, a task idle over 2 h), rolled up from the machines nested below it; `machinePage` and `machineStrip` page and count the machines entered from the In Progress one ([Machine rows](serving.md#machine-rows)) |
| `board` | `--state`, `--milestone`, `--label`, `--assignee` | `columns`: each `{state, name, tasks}`; a task is `{id, title, lane, assignee, milestone, labels, dependencies, waiting_on, prs, moves}` |
| `task show` | `TASK` | a task as above, with its `description`; a completed or archived task has only its `id` and where it settled as `lane` |
| `task moves` | `TASK` | `task`, `lane` and `moves`: each column the task may move to as `{allowed, reason, skill}`, as the agent meets it |
| `task move` | `TASK`, `TO`, `--session` | `ok`, `task`, `to`, `reason`, `skill` and `advice`: the move made, or the refusal and the skill that satisfies it (exit 1); exit 3 when the board has no writer |
| `task trace` | `TASK`, `--flow` | `task`, `flow` (null without `--flow`), `path` and `steps`; the Board's `{at, from, to}` lane changes, or with `--flow` that machine's `{at, event, state}`, oldest first; an unknown flow exits 4, a task never seen has an empty `path` |
| `machine list` | | `machines`: each `{name, states, tasks}` with its state ids and its live task count |
| `machine show` | `NAME` | `name`, `states` (each `{id, name, initial, final, count, tasks}`) and `transitions`; an unknown machine exits 4 and names those drawn |
| `machine validate` | `PATH...` | `ok` and `machines`: each `{path, ok, errors}`, an error `{file, line, message}` (`line` is null when the compiler cannot place it); exit 1 when any file is refused. A guard or action name is taken as the adapter's to register |
| `machine import mermaid` | `SOURCE`, `--out` | `written`: the new file, by default `.starpulse/machines/<name>.yaml`; an existing file is refused (exit 1), a missing source is exit 4 |
| `milestone list` | `--json` | `milestones`: each open milestone as `{id, title, outcome, specs, adrs, retro, description}`, by ascending number; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no milestones exits 3 |
| `milestone show` | `MILESTONE` | one milestone's record as above; one that is not open exits 4 |
| `milestone add` | `TITLE`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone`: the new id (the next number past every open and archived milestone); `--spec` and `--adr` repeat; a blank title exits 1 |
| `milestone edit` | `MILESTONE`, `--title`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone` and `changed`, the fields whose value differs; `--spec` or `--adr` given at all replaces that whole list, and a change that changes nothing writes nothing; naming no field exits 2, a refused change exits 1, an unknown milestone exits 4 |
| `milestone archive` | `MILESTONE` | `milestone`: moves the file to `archive/milestones/`; refusals as `milestone edit` |
| `doc list` | `--json` | `docs`: each open doc as `{id, title, type, created_date, updated_date, path}` with `path` relative to the board's `docs/`, by ascending number and without its body; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no docs exits 3 |
| `doc show` | `DOC`, `--json` | one doc's record as above plus its `body`, the text after its front matter; one that is not open exits 4 |
| `doc create` | `TITLE`, `--type`, `--folder`, `--body` | `doc`: the new id (the next number past every open and archived doc); `--type` is `specification`, `guide`, `readme` or `other` (the default), `--folder` a folder of plain names under `docs/` such as `specs`; a blank title, an unknown type or a folder that leaves `docs/` exits 1 |
| `doc update` | `DOC`, `--title`, `--type`, `--body` | `doc` and `changed`, the fields whose value differs; a change that changes nothing writes nothing, naming no field exits 2, a refused change exits 1, an unknown doc exits 4 |
| `doc archive` | `DOC` | `doc`: moves the file to `archive/docs/`; refusals as `doc update` |
| `runs list` | | `runs`: each workflow as `{workflow, status, raw, run_id, started_at, finished_at}` with `workflow` `<instance>/<workflow>`, and `error`, the runs adapters' error or null |
| `runs start` | `WORKFLOW` | `workflow` and `run_id`: starts `<instance>/<workflow>` through the server's Run now path, so only a workflow in the instance's `run_safe` starts and only from the loopback or private network, as JSON with no foreign `Origin` (exit 1 when refused); an instance with no start exits 3, a workflow outside `run_safe` exits 4 |
| `watch` | `--machine`, `--task` | one line per change after the connect snapshot, `{event, data}` with `event` `task`, `move`, `pulls`, `claim` or `dags` and `data` the server's delta; `--machine` keeps that machine's changes (`board` takes `task`, `pulls` and `claim`), `--task` that task's, and either drops `dags`; an unknown machine exits 4, the server ending the stream exits 3, and an interrupt exits 0 |
| `analytics health` | `--hours`, `--stuck-hours` | `now`, `window_s`, `stuck_after_s`, `states`, `throughput`, `stuck` and `warnings`, below |
| `analytics level` | `--hours` | `now`, `window_s`, `history_s`, `machine`, `goal`, `wip`, `throughput`, `time_in_state`, `aging`, `orbit` and `sources`, below; a window longer than the history exits 1 and a server with no level exits 3 |
| `analytics trajectories` | `--hours` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `variants`, `norm`, `outliers`, `chain`, `betweenness`, `bottleneck`, `loops` and `runs` (each `{source, task, path, back_edges, sccs, loops}`), below; refusals as `analytics level` |
| `analytics gates` | `--hours`, `--task` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `gates` and `runs`, below; `--task` keeps one run and exits 4 when it ended nowhere in the window; refusals as `analytics level` |
| `analytics forecast` | `--hours`, `--task` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `forecast` and `calibration`, below; `--task` keeps one run and exits 4 when it has no run still going; refusals as `analytics level` |
| `analytics what-if` | `--from`, `--to`, `--p`, `--hours` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `from`, `to`, `p`, `was`, `n`, `start`, `p_goal`, `expected_days` and `chain`, below; a what-if the chain cannot answer exits 1; refusals as `analytics level` |
| `config check` | `--config` | `ok`, `file`, `unknown_keys`, `errors` and `config`, the effective config with every default filled in (null when it does not load); exit 1 when it does not load |
| `demo` | `--out`, `--mockup`, `--server` | `written`: the HTML file; it reads the server's snapshot, or a design mockup directory with `--mockup` |
| `doctor` | `--config` | `ok` and `checks`: each `{check, status, reason}`, `status` `pass`, `warn` or `fail`; exit 1 when any fails, never for a warning |
| `skills list` | `--user` | `scope` and `skills`: each `{name, description, claude, codex}`, each harness `absent`, `installed`, `outdated` or `modified` |
| `skills install` | `--claude`, `--codex`, `--user`, `--force` | `scope` and `installed`: each `{harness, skill, path, was}`; exit 1 when a copy was modified since install |
| `help --agent` | | `exit_codes` and `verbs` |

`analytics health` reads `GET /api/analytics/health[?hours=N][&stuck_hours=N]` (a window of 168 hours and a stuck
threshold of 24 by default), the Board's flow health from the history's lane changes. `states` lists each Board state
with `wip`, the tasks in it now, and for a state that is not final the `visits`, `mean_s` and `max_s` of the stays that
ended inside the window or are still going, `open` of them: a task still in its state counts to now, so its stay is
flagged rather than left out. `throughput` is `{count, per_day}`, the entries into a final state in the window.
`stuck` lists each task whose current stay in a state that is neither the first nor a final one has lasted
`stuck_hours` or longer, longest first, each `{task, state, since, dwell_s, counted_to_now}`. `warnings` carry each
gap the history recorded (`kind` `gap`: entries trimmed before it read them, so counts may miss them) and each lane
the Board machine has no state for. History starts at a task's first recorded lane change, so a stay before it is not
counted. The endpoint is 400 for an `hours` or `stuck_hours` that is no positive number, and 501 when the history
does not list every task's lane changes through `lane_rows(since=None)` and `gaps()`; `since`
is an epoch the Ledger passes so it reads only its last 24 hours, and None asks for every change.

`analytics level` reads `GET /api/level[?hours=N]` (a window of 168 hours by default), served by a hub (`serve --hub`)
whose config has a `[level]` table. It counts the level's machine on the Backlog flow metric definitions, merged across
the sources that forward to the hub, a source being the prefix of an event id (`<source>/<id>`; `unattributed` when
none). `wip` is the runs now in a working state (`orbit.working`, else every state that is neither initial nor a
terminal), `throughput` the entries into the goal in the window (a run that settled from the goal, into a final state
no terminal names, is still in it, so seeing it in the goal again is no second entry), `time_in_state` each non-final
state's stays clipped to the window, and `aging` each working run's age since its first working step, where its cycle
time starts, against `threshold_s`, the
85th-percentile cycle time of the trailing 12 weeks (null with no completion to measure). `orbit` totals the ended runs
per terminal and the working time per working state, and each of `sources` carries its `ended` runs with
`terminal_share`, its `dwell` per working state with `time_share`; a set of shares sums to 1, and is empty, not zero,
for a source with nothing ended or worked. `level` echoes the config the page draws from (`title`, `subject`, `runs`,
`gates`, `terminals` with their roles, `orbit.suns` and `orbit.working`, `facets`, `activity.measure` and
`activity.pace`), each source's `shared` is whether it has a Board of its own (false for `unattributed`), and
`arrivals` lists each run's entry into a terminal inside the window as `{source, state, at}` (epoch seconds, oldest
first), the comets the page replays. History begins at the first event the hub holds: a window longer than it is
refused (exit 1, the error naming the history's hours, `history_s` in the HTTP body), never padded with zero days. A
server with no level is 404 (exit 3).

`analytics trajectories` and `analytics gates` read `GET /api/level/trajectories[?hours=N]`, with the window, history and
refusals of `analytics level`. They cover the runs of the level's machine that ended in a terminal inside the window,
each a whole path with its self-loops collapsed. `variants` counts each distinct path (`{path, count, share}`, most
common first) and `norm` is the most common; `outliers` ranks the other runs by Levenshtein distance from the norm,
furthest first. `chain` is an absorbing Markov chain over the observed transitions, terminals absorbing: per state
`expected_days` to finish and `p_goal`, solved from the fundamental matrix N = (I - Q)^-1 with N times the mean stay
and N times the chance of stepping into the goal. `betweenness` is Brandes centrality per state on the transition
graph and `bottleneck` the state holding the most path time, `{state, path_days}`. `loops` is the rework: each back-edge
(`from`, `to`) some run took, with the `runs` that took it and the `trips` and `days` summed over them, the longest first. A
run's own `back_edges` and `sccs` count the back-edges of a depth-first search from its first state and the strongly
connected components of two states or more in the graph of its own steps; its `loops` list each back-edge with its
`trips` and the `days` they took, from the target's previous visit to each return; the step that first enters a state is no
trip, so a back-edge no run went round again is not listed. They come from each run's own graph and
never the union of every run's, so a cycle only two runs together close is not reported. `gates` has one entry per
configured gate over the runs that reached the goal: how many `crossed` it, how many had to cross it (`mandatory`),
`bypassed`, `bypassable`, and a `witness` `{task, path}`, the shortest path a bypassing run could have taken to the
goal without the gate. Dominators are computed per run, on the graph of that run's own steps (`runs`: each
`{source, task, path, reached_goal, gates}` with each gate's `crossed`, `mandatory`, `dominators` (the states every
path from the run's first state to the gate crosses), `post_dominators` (every path from the gate to the goal) and
`witness`), never on the union of every run's graph, which holds paths no run took. A gate a run visited only on a
detour is bypassable. A trajectory joined with its agent sessions is not computed here: the history keeps task steps,
not sessions.

`analytics forecast` reads the same route's `forecast` and `calibration`. `forecast` is each run still going (its last
state neither a terminal nor final), by task: `{source, task, state, loops, since, p, p_goal, expected_days, n,
pooled}`. `loops` is the rework loops it has gone round so far, the trips of the back-edges of its steps up to now, and
the chain the forecast reads is fitted on the ended runs with each state split by that count, two and more sharing a row,
so a third review round is not read as the first. `p` is the chance of ending in each terminal and `expected_days` the
days to finish, from the row's N = (I - Q)^-1; `n` is how many times the ended runs left that row. A row left fewer than
5 times is `pooled`: the state's own row, whatever the loop count, answers; a state no ended run left has null chances
and `n` 0. It is a probability with its sample size, never a status. `calibration` scores the forecast: the latest fifth
of the ended runs by when they ended are held out (`held_out`, the rest being `fit`), each of their steps before the end
is forecast from a chain fitted on the others, and `deciles` bins those `predictions` by forecast chance of the goal,
each `{low, high, n, runs, predicted, observed}` with `predicted` the mean forecast and `observed` the share of the
goal reached; `calibrated` is whether every decile holding a forecast is within 10 points, null with none.

`analytics what-if` reads `GET /api/level/what-if?from=&to=&p=[&hours=N]`: the chain of the runs that ended in the
window with `from -> to` at probability `p` (`was` the observed one over `n` exits), `from`'s other exits keeping their
shares of the rest. `p_goal` and `expected_days` are `{before, after, change}` from `start`, the state most ended runs
began in, and `chain` is the changed chain per state. A state no ended run left (a terminal `to` needs none), `to` the
same as `from`, a `p` outside 0 to 1, a transition that is its state's only exit, or a chain that would never finish is
400 (exit 1).

A move carries the actor that makes it. The machine YAML names, per event, who fires it (`writers`), and each move
the server offers lists them as `writers`; `POST /api/move` takes `{task, to, actor}` with `actor` `operator` when
absent, which is what the page sends. The server refuses an actor outside the event's writers before the board
writer is asked, so a move declared for `operator` alone (sending an In Progress task back to Ready) is refused to
`starpulse task move`, which always moves as `agent`. A board adapter's `writer` receives that actor as its third
argument: `writer(task, status, actor)`. `/api/move` is unauthenticated on the LAN, so this stops an agent's
accident, not an adversary.

The same file names, in a `cues:` block, the workflows an event cues: each entry is `{event, dag, on, resolves, grace}`, with
`dag` as `<instance>/<workflow>`, `on` the occasion the page shows (`push to main`) and `resolves` either `forced` (a
failed run stays pinned until a forced rerun) or `next` (it clears on the DAG's next run). `grace` is optional, in seconds, and defaults to 300: a merge whose
cued run has not started that long after it shows `overdue` on the Ledger. The cued event must reach
exactly one state, beside which the page draws the cue; a file with no block has no cues.

A move may also name the mover's session: `POST /api/move` takes `{task, to, actor, session}`, and `starpulse task move`
sends `--session`, else `STARPULSE_SESSION`. A move that names one calls the writer with it as a fourth argument,
`writer(task, status, actor, session)`; one that names none calls it with three, so a writer written before sessions
keeps working. The writer records the session as the task's holder when the move is a claim, `BoardTask.holder`
carries it back, and a `Written.advice` string rides in the move's answer (`advice` in the CLI document, empty when
the writer has none). The native and Backlog.md adapters' writers record the holder as a `**Holder:** <session>` line in the
task's notes, in the same edit as the `In Progress` status, because the Backlog CLI drops a frontmatter key it
does not know.

`doctor` runs every check even when one fails, so one call names every fault. The checks: `config` (the config file
loads), `server` (it answers `/api/snapshot`), `adapter:board` and one `adapter:<name>` per `[[runs]]` instance (it is
producing: the Board is read, the instance lists workflows and reports no error), and `gh` (installed and logged in,
which the pull request reader needs).

Two contract checks read the config against the machines' cues. `cue:<instance>/<workflow>` runs once per cued
workflow: it fails when no instance lists the workflow or when a `[runs.commit]` key (`after`, `before`, `force`,
`task`) names a parameter the workflow does not declare (read from Dagu's `dag.params`), and it warns, without failing
the run, when the instance has no `after` key, so its runs pair with a merge only by the time they started.
`repo:<name>` runs once per `[[repos]]` entry and fails when its `path` is not a submodule of the repository `doctor`
runs in. Neither runs while the config or the server cannot be read.

`GET /api/doctor` serves those two kinds of check as `{ok, checks: [{check, status, reason}]}`, read from the server's
own snapshot and config and held for a minute; the page draws it as the Ledger's doctor banner. A server with no
contract to read answers `{ok: true, checks: []}`.

`skills` reads no server. The package bundles four skills: `operating-starpulse-board` (what to work next, why a task
cannot move, moving it), `authoring-starpulse-machines` (machine YAML, writers, guards, subflows, `machine validate`
and `machine import mermaid`), `writing-starpulse-adapters` (the board, machine-events and runs contracts, the adapter
kit, `emit`) and `setting-up-starpulse` (starting the server, config, `doctor`), and `skills install`
copies them to `.claude/skills` (`--claude`) or `.agents/skills` (`--codex`) in the working directory, or with `--user`
to `~/.claude/skills` or `~/.agents/skills`. An install records what it wrote, so a copy you edited afterwards is
refused (exit 1) until you pass `--force`, while one the package has since updated is replaced; `skills list` reports
which of the four each copy is.

## The pull-request store

With `gh` available, `serve` keeps a store of pull requests (table `starpulse_pull_requests`) and refreshes it every
minute, one GraphQL query per repository: every open pull request, plus any other pull request updated since the newest
`updatedAt` the store holds for that repository. A merged or closed record is final and is never read again. An open
pull request is re-read on every refresh even when its `updatedAt` is unchanged, because a check finishing does not
bump it. A pull request the store has not seen yet costs one follow-up query, so a cold store costs two. The
repositories are those of open tasks' pull request links, the `[[repos]]` entries under a linked owner, and those
already stored. Each query's `rateLimit` cost is logged (`pull requests: <repo> query cost N, remaining N, resets T`).
A repository with more than 100 open pull requests is read for the first 100, with a warning.

`GET /api/pulls[?repo=owner/name][&number=N][&state=OPEN|MERGED|CLOSED][&body_contains=text]` serves the store,
`{pulls: [...]}`, ordered by repository then number. Each record holds `repo`, `number`, `state`, `isDraft`,
`mergeable`, `baseRefName`, `headRefOid`, `body`, `checks` (`pass`, `failing`, `pending` or `none`), `requiredChecks`
(`{name, result}`), `threads` (open review threads), `updatedAt` and `fetchedAt` (epoch seconds of the read). A `number` that is not an
integer or an unknown `state` answers 400.

`GET /metrics` serves Prometheus text: `starpulse_pull_store_age_seconds{repo="owner/name"}`, the seconds since the newest
record of each repository holding an open pull request was read. The refresh reads those every minute, so a value past a
few minutes means the refresh stopped; a repository with none open is left out, because nothing rewrites it.

`waiting_on` is the dependencies not yet completed. `prs` are the task's pull request links, each with the checks,
merged state, open review threads and commits behind `main` the server last read when it has them.
