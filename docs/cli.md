# Agent command line

An agent reads and works the board through `starpulse` verbs, each printing one JSON document.

```sh
starpulse board --milestone launch --label api   # tasks per column, with dependencies, pull requests and moves
starpulse search "signing keys" --limit 5        # tasks holding every word in title, description, criteria or notes, best first
starpulse task show PROJ-45                      # one task: lane, what it waits on, pull requests, moves
starpulse task moves PROJ-45                     # every column it may move to, allowed or refused to the agent
starpulse task move PROJ-45 review               # move it as the agent; a refusal is the verdict, exit 1
starpulse task trace PROJ-45 --machine in-progress  # where the task has been: Board lanes, or one machine's events
starpulse task create "Rotate the secret" --priority high --label ops --ac "It rotates"  # open a task; its id
starpulse task edit PROJ-45 --title "Rotate the signing secret" --label ops   # one write, refused whole when stale
starpulse task show PROJ-45 --markdown          # the task rendered as markdown, in `markdown`
starpulse task edit PROJ-45 --editor            # break-glass: edit that rendering in $VISUAL/$EDITOR, import it as events
starpulse task edit PROJ-45 --check-ac 2 --remove-dod 1 --append-notes "Verified."  # items by number, a notes line
starpulse task profile PROJ-45 @agent-standard-high  # route it to an agent profile
starpulse task archive PROJ-45 --reason "superseded"  # archive it from any lane, with the reason as a comment
starpulse task verdict PROJ-45 live pass --evidence "up=1"  # record a post-merge check's verdict on its task
starpulse task miss PROJ-45 live --title "Repair live"  # file the fix and record the MISS verdict, both or neither
starpulse task restore PROJ-45                   # return an archived task to the board, unchanged
starpulse task retire PROJ-45                    # take a finished task off the board into the history store
starpulse task retired PROJ-45                   # read a retired task's file name and text back
starpulse task import-retired "retired/PROJ-3 - Old.md"  # keep a retired task file a client held
starpulse task complete PROJ-45                  # move a Done task to the completed tasks
starpulse task checkpoint-ac PROJ-45 2 "pytest exits 0"  # check criterion #2 and record the evidence
starpulse machine show in-progress               # a machine's states, transitions and the tasks now in each
starpulse milestone list                         # every open milestone: title, outcome, specs and ADRs
starpulse milestone add "Launch" --outcome "Shipped" --spec "doc-1 - plan" --adr docs/adr/a.md
starpulse doc list                               # every open doc: title, type, dates and path, without bodies
starpulse doc create "Plan" --type specification --folder specs --body "# Plan"
starpulse runs list                              # each workflow as <instance>/<workflow> with its latest status
starpulse runs start prod/nightly                # start a run-safe workflow through Run now; its run id
starpulse watch --task PROJ-45                   # one JSON line per change, until you stop it: wait without polling
starpulse analytics health --hours 72            # dwell and WIP per state, throughput and stuck tasks, with gap warnings
starpulse analytics steps --hours 24             # one row per model request: skill in force, activities, keys, tokens
starpulse analytics transitions --hours 168      # per kind x size x skill: steps, wasted-step rate, agent seconds, peak context
starpulse analytics cells --hours 720            # per kind x size: median steps per clean completion on a latest-fifth holdout
starpulse analytics scores --repo o/r --hours 166  # per kind x size x profile: mean task score, with GitHub commits-after-ready and time-to-merge
starpulse analytics graph --hours 168            # per transition: each activity edge with its run count, judgement cuts marked
starpulse analytics stages --hours 168           # sub-stages of the stretches no skill governs, and their stability from the week before
starpulse analytics diff --hours 168             # per transition: the reference run against the slowest clean run
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
`http://localhost:8766`. `STARPULSE_TOKEN`, when set, is sent as a bearer token on every request.
Each writes one JSON document to stdout and nothing to stderr, except `watch`, which writes
one JSON line per change; an error is `{"error": "...", "code": "..."}`. The exit code is 0 for success, 1 for a refused or invalid request, a refused move or a failed `doctor` check, 2 for a usage
error, 3 when the server is unreachable (the error names the address tried) or has no board writer and 4 for something not found. A write the server answers `503` with `Retry-After` while it restarts or replays its feed fails with code `unavailable` and a
`retry_after` key (seconds) in the error, for a caller to send it again. A verb
reads the server on every call and keeps nothing, and `help --agent` is generated from the command parser, so it
lists exactly the verbs there are.

| Verb | Arguments | Document |
|---|---|---|
| `snapshot` | | the server's full snapshot (`/api/snapshot?view=full`, [Cold done tasks](serving.md#cold-done-tasks)): `graphs`, `flows`, `dags`, `pools`, `pulls`, `claims`, `settled`, ...; each `flows` entry but the Board's also carries `ties` (`{kind, machine, state, count, dag, when}`: `declared`, `observed` or `dag`), `parent`, `depth`, `chain`, `nested`, `last` and `stuck` (`{machine, state, since}`, a task idle over 2 h), rolled up from the machines nested below it; `machinePage` and `machineStrip` page and count the machines entered from the In Progress one ([Machine rows](serving.md#machine-rows)) |
| `board` | `--state`, `--milestone`, `--label`, `--profile`, `--assignee`, `--type` | `columns`: each `{state, name, tasks}`; a task is `{id, title, lane, phase, substate, done_at, profile, assignee, milestone, type, labels, dependencies, waiting_on, criteria, pause_reason, prs, moves}`, `phase` the state of an `in_progress` task's In Progress machine and `substate` the state of that phase's submachine (null when it has none; only the current phase's submachines count); while a submachine holds the task and the In Progress machine has no state for it, `phase` is the state that submachine is linked to, `done_at` the ISO time a `done` task entered the lane (null otherwise), `profile` the agent profile it is routed to and `assignee` the session that last claimed it (empty when none has), `criteria` each acceptance criterion as `{text, checked}`, `pause_reason` why a `needs_attention` task waits for a person (empty otherwise), `--profile` keeping only tasks routed to that profile, `--assignee` only that session's tasks (`--holder` and a `--assignee` value starting with `@` are the one-release aliases of the old keys) and `--type` only tasks of that type; `--milestone` also lists the milestone's done tasks past their hot day (`/api/done` cards: no `dependencies`, `criteria`, `prs` or `moves`) |
| `search` | `QUERY...`, `--limit`, `--label`, `--finished-within-days` | `query` and `hits`: each task holding every word of the query as `{task, title, lane, score, snippet}`, best match first, at most `--limit` (1 to 100, default 10); each `--label` keeps only the tasks carrying it, and `--finished-within-days N` drops a task that finished more than `N` days ago; a blank query, a limit out of range or a window that is not a positive integer exits 1, and a server that keeps no index exits 3 |
| `task show` | `TASK` | a task as above, with its `description`, in which each bare `TASK-N` is a link to the task's card on the Board and each `#N` (three digits or more) a link to the task's pull request of that number, while code spans, existing links and bare URLs stay as written; a task done over 24 h ago is read whole from its board record; a completed or archived task has only its `id` and where it settled as `lane` |
| `task moves` | `TASK` | `task`, `lane` and `moves`: each column the task may move to as `{allowed, reason, skill}`, as the agent meets it |
| `task move` | `TASK...`, `TO`, `--session` | `ok`, `task`, `to`, `reason`, `skill` and `advice`: the move made, or the refusal and the skill that satisfies it (exit 1); exit 3 when the board has no writer. Several tasks move in one write (`POST /api/move` with `tasks`), each judged on its own: the output is `moved` and `refused`, each refused task with its reason, and a refused task exits 1 while the others stay moved |
| `task trace` | `TASK`, `--machine` | `task`, `machine` (null without `--machine`), `path` and `steps`; the Board's `{at, from, to}` lane changes, or with `--machine` that machine's `{at, event, state}`, oldest first; an unknown flow exits 4, a task never seen has an empty `path` |
| `task create` | `TITLE` or `--batch FILE`, `--description`, `--priority`, `--impact`, `--urgency`, `--milestone`, `--profile` (alias `--assignee`), `--status`, `--type`, `--label`, `--dependency`, `--ac`, `--reference`, `--documentation`, `--dod` | `task`: the new id (the next number past every open, completed, archived and retired task); the task is written whole in one write, in the board's first lane or the lane `--status` names, so no second write is needed to finish it and a refused create leaves no task; `--label`, `--dependency`, `--ac`, `--reference`, `--documentation` and `--dod` repeat, the criteria and Definition of Done items numbered in order; a `--documentation` that is an open doc's id (`doc-12`) is stored as that doc's file, and an id no open doc has exits 1; `--priority`, `--impact` and `--urgency` are each `high`, `medium` or `low` (Impact and Urgency set the task's Priority weight in the scheduler's admission order); a blank title or an unknown priority exits 1; a board that cannot create tasks exits 3; `--batch FILE` (`-` for stdin) takes a JSON list of task specs (`title`, the detail fields, an optional `ref`) and creates them in one request, a spec's dependency `ref:<label>` becoming the new id of the earlier spec with that `ref`; `task` is then the list of new ids, and a refused spec leaves the others created, exits 1 and names each refused spec's position and reason in `refused` |
| `task edit` | `TASK`, `--title`, `--type`, `--priority`, `--milestone`, `--label`, `--dependency`, `--reference`, `--documentation`, `--modified-file`, `--description`, `--plan`, `--notes`, `--append-notes`, `--final-summary`, `--ac`, `--reword-ac`, `--remove-ac`, `--check-ac`, `--uncheck-ac`, `--dod`, `--reword-dod`, `--remove-dod`, `--check-dod`, `--uncheck-dod`, `--comment`, `--base` | `task` and `changed`, the fields whose value differs, in the record's field names (`labels`, `modifiedFiles`, `finalSummary`); every field given is written in one write, or none: `--base` is a JSON object of the values the caller read, else the task is read at the call, and the edit is refused whole (exit 1, the error naming the stale fields) when any field it changes no longer has its base value; a list flag given at all replaces that whole list, a blank value clears the field, and a change that changes nothing writes nothing, except that a non-blank `--comment` is still written and `changed` is `[]`; `--ac` and `--dod` add an unchecked item, `--reword-ac N:TEXT` and `--reword-dod N:TEXT` replace the wording of item `#N`, and `--remove-*`, `--check-*` and `--uncheck-*` take an item's number as the task shows it before the edit, each repeatable and applied to the list as read (a removal renumbers the items from 1; a number the task lacks exits 1 and writes nothing, a reword with no `N:` exits 2); `--append-notes` adds a line to the end of the Implementation Notes whatever they hold when the write lands, leaves the text before it as written, is not checked against `--base`, and reports as `notes`; naming no field or a `--base` that is no JSON object exits 2, a blank title exits 1, an unknown task exits 4, a board that cannot read or edit tasks exits 3 |
| `task archive` | `TASK...`, `--reason` | `archived`: each task moved from its lane to the board's archive in one write (`POST /api/archive` with `tasks`), a key the board refuses leaving the others archived and the verb refused (exit 1) with `archived` and `refused`, each refused key with its reason; a non-blank `--reason` recorded on it as the comment `Archived: <reason>`; each open (not Done) task that lists it as a dependency has that dependency removed with a comment saying why, a Waiting one left with no dependency and no Start Criteria moves to Ready, and the output names them; an unknown task exits 4, a board that does not archive tasks exits 3 |
| `task verdict` | `TASK`, `CHECK`, `pass` or `miss`, `--evidence`, `--fix` | `task`, `check`, `verdict`: the verdict (`PASS` or `MISS`) recorded as a comment on the task that opens `[post-merge-check] <CHECK> <VERDICT>`, a miss naming its `--fix` task on a `Fix: <task>` line and `--evidence` after them. The task's `## Post-merge Checks` block must declare `CHECK` and hold no verdict for it, since a verdict is final: a second, an undeclared check or a malformed block exits 1; a `miss` without `--fix` exits 1; an unknown task or `--fix` task exits 4, a board that does not edit tasks exits 3 |
| `task miss` | `TASK`, `CHECK`, `--title` and the `task create` detail flags, `--evidence` | `task`, `check`, `verdict` (`MISS`), `fix`: the new task, filed from `--title` and the detail flags, and the MISS verdict naming it recorded on `TASK` in one call. A fix whose verdict is refused is archived again, so a refused miss leaves neither; the refusals of `task verdict` exit 1, a board that cannot edit, archive and create tasks exits 3 |
| `task restore` | `TASK` | `task`: the archived task's file moved back to the board's tasks, byte for byte; a task whose number is already open, whose file name is taken or that is not archived exits 1, a retired task is returned the same way; a board that does not restore tasks exits 3 |
| `task retire` | `TASK` | `task`: a finished task (Done, in the completed tasks or archived) taken off the board into the server's history store, its file kept byte for byte under its name, so the board's reads and numbering scan fewer files while a new task still numbers past it and a transition rule's dependency on it keeps the state it was retired in; an open or unknown task, a number already kept with other text, or a board not yet started on its store exits 1 and keeps the file; a board that does not retire tasks exits 3 |
| `task retired` | `TASK` (optional) | `tasks`: every retired task, or the one `TASK` names (matched ignoring case), each `{task, name, text}` with its file name and text; an unretired task gives `[]`; a board that keeps no retired tasks exits 3 |
| `task import-retired` | `FILE...` | `tasks`: the id each file's front matter names, each file kept in the history store as `task retire` keeps one, under its own name and byte for byte; the same file again is accepted, so a run a refusal stopped can be given the same files again; a file that is not there exits 2 before any is sent, a file with no id, a task on the board or other text under a kept number exits 1, a board that does not import retired tasks exits 3 |
| `task complete` | `TASK` | `task`: a Done task moved to the board's completed tasks, where it is still read and edited; a task that is not Done (or already completed) is refused with the board's reason and skill (exit 1), an unknown task exits 4, a board that does not complete tasks exits 3 |
| `task claim` | `TASK`, `--session`, `--harness` | `ok`, `task`, `to`, `assignee`, `reason` and `skill`: the task moved to In Progress with the session (an opaque string; `--session`, else `STARPULSE_SESSION`, required) recorded as its `assignee`; a claim by the holder it already has succeeds without a write; a task held by another session (or In Progress with no holder), or a session already holding another In Progress task, is refused with the holder or task named (exit 1) and nothing written; an unknown task exits 4, a board that cannot move tasks exits 3 |
| `task park` | `TASK`, one of `--until-task TASK` or `TASK#K` (repeatable), `--until CRITERION` (repeatable YAML or JSON) and `--operator REASON`, and `--comment` | `ok`, `task`, `to`, `reason` and `skill`: the task paused for exactly one typed reason, which picks the lane in the same write: `--until-task` adds the named tasks to its dependencies (`TASK#K` also records that it needs only criterion K of that task, and is refused when K is absent or already checked) and `--until` replaces its start criteria (each with a unique `id` and a `kind`), both moving it to `waiting`; `--operator` moves it to `needs_attention` with the reason as its pause reason. No reason or more than one exits 2; a named task that is already Done or is the task itself, criteria on a task that already waits on a task, or criteria of the wrong shape is refused (exit 1) with nothing written; an unknown task exits 4, a board that cannot edit tasks exits 3 |
| `task review` | `TASK`, `--ref` (repeatable), `--summary`, `--comment` | `ok`, `task`, `to`, `reason` and `skill`: the task moved to Review with the `--ref` evidence added to its references and `--summary` as its final summary; the board's `[[board.guards]]` judge the record the move would leave, and a rule's refusal exits 1 with its reason and skill and writes nothing; an unknown task exits 4, a board that cannot edit tasks exits 3 |
| `task checkpoint-ac` | `TASK`, `CRITERION`, `EVIDENCE` | `task`, `criterion` and `changed` (`["acceptanceCriteria"]`, or empty when the criterion was already checked): the criterion `#CRITERION` checked and the comment `Verified AC #N: <evidence>` appended in one write, with the refusals of `task edit`; a criterion the task lacks exits 1 and writes nothing, blank evidence exits 2, an unknown task exits 4, a board that cannot read or edit tasks exits 3 |
| `task edit --editor` | `TASK` | `task` and `changed`: opens the task rendered as markdown (the same rendering as `task show --markdown`) in `$VISUAL`, else `$EDITOR`, else `vi`, and imports what the operator changed as the events of an edit, by actor `operator` with writer `break-glass`; an edit that removes or adds a section or field line the rendering cannot map back, or changes `Status` (a move is not an edit), is refused naming it with code `refused` and writes nothing; no change writes nothing |
| `task profile` | `TASK`, `PROFILE` | `task`, `profile` and `changed` (`["profile"]`, or empty when the profile already is that value): the edit of the profile alone, with the refusals of `task edit`; a blank profile clears it |
| `machine list` | | `machines`: each `{name, states, tasks}` with its state ids and its live task count |
| `machine show` | `NAME`, `--format json\|dot` | `name`, `states` (each `{id, name, initial, final, count, tasks}`), `transitions` (each `{source, target, event}` and the `cite` its YAML gives), and the `submachines`, `launches` and `writers` the machine declares; `--format dot` adds `format` and `diagram`, the machine as Graphviz DOT source; an unknown machine exits 4 and names those drawn |
| `machine validate` | `PATH...` | `ok` and `machines`: each `{path, ok, errors}`, an error `{file, line, message}` (`line` is null when the compiler cannot place it); exit 1 when any file is refused. A guard or action name is taken as the adapter's to register |
| `machine import mermaid` | `SOURCE`, `--out` | `written`: the new file, by default `.starpulse/machines/<name>.yaml`; an existing file is refused (exit 1), a missing source is exit 4 |
| `milestone list` | `--json` | `milestones`: each open milestone as `{id, title, outcome, specs, adrs, retro, description}`, by ascending number; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no milestones exits 3 |
| `milestone show` | `MILESTONE` | one milestone's record as above; one that is not open exits 4 |
| `milestone add` | `TITLE`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone`: the new id (the next number past every open and archived milestone); `--spec` and `--adr` repeat; a blank title exits 1 |
| `milestone edit` | `MILESTONE`, `--title`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone` and `changed`, the fields whose value differs; `--spec` or `--adr` given at all replaces that whole list, and a change that changes nothing writes nothing; naming no field exits 2, a refused change exits 1, an unknown milestone exits 4 |
| `milestone archive` | `MILESTONE` | `milestone`: moves the file to `archive/milestones/`; refusals as `milestone edit` |
| `doc list` | `--json` | `docs`: each open doc as `{id, title, type, created_date, updated_date, path}` with `path` relative to the board's `docs/`, by ascending number and without its body; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no docs exits 3 |
| `doc show` | `DOC`, `--json` | one doc's record as above plus its `body`, the text after its front matter; one that is not open exits 4 |
| `doc create` | `TITLE`, `--type`, `--folder`, `--body`, `--task` | `doc`: the new id (the next number past every open and archived doc); with `--task`, also `task` and `changed`, the doc's file added to that task's documentation in one edit; `--type` is `specification`, `guide`, `readme` or `other` (the default), `--folder` a folder of plain names under `docs/` such as `specs`; a blank title, an unknown type or a folder that leaves `docs/` exits 1 |
| `doc update` | `DOC`, `--title`, `--type`, `--body` | `doc` and `changed`, the fields whose value differs; a change that changes nothing writes nothing, naming no field exits 2, a refused change exits 1, an unknown doc exits 4 |
| `doc archive` | `DOC` | `doc`: moves the file to `archive/docs/`; refusals as `doc update` |
| `doc restore` | `DOC`, `--folder` | `doc`: moves the archived file back under `docs/`, byte for byte, into `--folder` (a folder of plain names such as `specs`; `docs/` itself by default); a doc that is already open, a destination that exists, an unarchived id or a folder that leaves `docs/` exits 1, a board that does not restore docs exits 3 |
| `runs list` | | `runs`: each workflow as `{workflow, status, raw, run_id, started_at, finished_at}` with `workflow` `<instance>/<workflow>`, and `error`, the runs adapters' error or null |
| `runs start` | `WORKFLOW` | `workflow` and `run_id`: starts `<instance>/<workflow>` through the server's Run now path, so only a workflow in the instance's `run_safe` starts and only from the loopback or private network, as JSON with no foreign `Origin` (exit 1 when refused); an instance with no start exits 3, a workflow outside `run_safe` exits 4 |
| `watch` | `--machine`, `--task` | one line per change after the connect snapshot, `{event, data}` with `event` `task`, `move`, `pulls`, `claim` or `dags` and `data` the server's delta; `--machine` keeps that machine's changes (`board` takes `task`, `pulls` and `claim`), `--task` that task's, and either drops `dags`; an unknown machine exits 4, the server ending the stream exits 3, and an interrupt exits 0 |
| `analytics health` | `--hours`, `--stuck-hours` | `now`, `window_s`, `stuck_after_s`, `states`, `throughput`, `stuck` and `warnings`, below |
| `analytics steps` | `--hours` | `now`, `window_s` and `steps`, each `{harness, session, task, at, model, origin, skill, activities, keys, tokens, captured}`, below; a window that is no positive number or is longer than the telemetry history exits 1 and a server that receives no telemetry exits 3 |
| `analytics transitions` | `--hours` | `now`, `window_s` and `transitions`, each `{kind, size, skill, tasks, steps, side_steps, wasted_steps, wasted_rate, agent_s, peak_context}`, below; refusals as `analytics steps` |
| `analytics cells` | `--hours` | `now`, `window_s` and `cells`, each `{kind, size, n, completions, clean_rate, holdout, median_steps, median_operator_prompts, median_steps_before_edit}`, below; refusals as `analytics steps` |
| `analytics scores` | `--hours`, `--repo` (required) | `now`, `window_s`, `scores`, each `{kind, size, profile, n, score, off_arm}`, and `verdicts`, each `{kind, size, baseline, profile, n, baseline_n, verdict, p_non_inferior, p_worse}`; exit 3 when GitHub is unreachable, refusals as `analytics steps` |
| `analytics graph` | `--hours` | `now`, `window_s` and `graph`, each edge `{kind, size, skill, source, target, runs, count, share, cut}`, below; refusals as `analytics steps` |
| `analytics stages` | `--hours` | `now`, `window_s` and `stages`, each `{kind, size, stage, runs, median_activities, previous_runs, previous_median_activities, stability}`, below; the history must hold twice the window, else refusals as `analytics steps` |
| `analytics diff` | `--hours` | `now`, `window_s` and `diff`, each `{kind, size, skill, runs, conformant, reference, slow, slow_only, reference_only}`, below; refusals as `analytics steps` |
| `command run` | `NAME`, `--task`, `--arg NAME=VALUE`, `--config`, `-- ARGS` | `name`, `argv`, `exit` and `seconds`: runs the argv `[project.commands]` maps `NAME` to, offline, in this directory, with no shell, its output on stderr. Exit 0 when the child succeeds, 1 when it fails (its code is in `exit`), 2 when a placeholder has no value or an element has a brace that is not a placeholder (write a literal brace as `{{` or `}}`), 3 when `argv[0]` cannot run, 4 when `NAME` has no entry, with `"fallback": "AGENTS.md"` |
| `config check` | `--config` | `ok`, `file`, `unknown_keys`, `errors` and `config`, the effective config with every default filled in (null when it does not load); exit 1 when it does not load (a malformed `[project.commands]` entry included), or when a built-in board's machine names a writer workflow no `[[runs]]` domain lists, which `serve` refuses to start on |
| `demo` | `--out`, `--mockup`, `--server` | `written`: the HTML file; it reads the server's snapshot, or a design mockup directory with `--mockup` |
| `doctor` | `--config` | `ok` and `checks`: each `{check, status, reason}`, `status` `pass`, `warn` or `fail`; exit 1 when any fails, never for a warning |
| `skills list` | `--user` | `scope` and `skills`: each `{name, description, claude, codex}`, each harness `absent`, `installed`, `outdated` or `modified` |
| `skills install` | `--claude`, `--codex`, `--user`, `--force` | `scope` and `installed`: each `{harness, skill, path, was}`; exit 1 when a copy was modified since install |
| `help --agent` | | `exit_codes` and `verbs` |

`search` reads `GET /api/search?q=QUERY[&limit=N][&label=L]...[&finished_within_days=N]`: the words of `q` are each a quoted phrase and all must match, so
punctuation (`PROJ-45`, `NEAR`, `title:`) is text and never query syntax. A task is searchable by its key, title,
description, acceptance criteria and notes (its `**Assignee:**` claim marker, or the legacy `**Holder:**`, is not text), and a match in the title
ranks above one in the description, which ranks above one in a criterion or a note; words are matched by their
stem (`rotation` finds `rotate`). `score` is higher for a better match, `lane` is the lane the task is in now (or
`completed` or `archived` once it settled) and `snippet` is the text around the match. The index is a SQLite FTS5
table in the instance's own database, filled from the board adapter on the first read, so every adapter (native,
Backlog.md, Jira) is searched the same way, and kept current as each task is placed, edited, moved or retracted; a
task placed again unchanged, as every task is on a restart, writes nothing. A SQLite built without FTS5 serves none: the route answers 404 and the verb exits 3.

Without filters a search reaches every task, open or settled, of any age. Each `label` (repeatable) keeps only the
tasks carrying that label, matched whole (`disk` does not match `disk-usage`). `finished_within_days=N` keeps every
open task and drops one that finished more than `N` days ago: a completed or archived task finished when it settled
(a settled task the board gives no time for counts as older than any window), and a task in the done lane when it
entered that lane (when the lane history does not date that entry, the first time the index saw it there). A task
keeps its earliest finish time until it reopens, so a restart moves none later. Both narrow the lexical and the vector hits alike. The index keeps each task's labels and finish
time beside its text, outside the text's digest, so an index written before them gains them as each task is next
placed, as every task is on a restart, without embedding anything again.

The `[search]` table's `embeddings_url` is optional ([Config file](serving.md#config-file)). Unset, ranking is the
lexical order above and nothing calls out. Set, `serve` sends each task's title and description to that
OpenAI-compatible endpoint in the background, one task to a request so a query never waits behind a batch, and keeps one vector per task and `model`; a query is then embedded once
and its lexical hits (up to the 50 best) are ordered by half their bm25 score, relative to the best hit's, and half the cosine similarity of
their vector to the query's, so `score` is that blend. A task whose vector is not stored yet counts as no similarity.
A task that holds none of the query's words is a hit too when the cosine similarity of its vector to the query's is at
least 0.55, so a reworded description still finds the task it rewords; its `snippet` is the task's opening and its
`score` is half that similarity. The server holds the unit vectors as one matrix and scores them in a single product, reading again only the vectors
of tasks a write changed, so a search over thousands of tasks takes milliseconds and never waits for a write. Without a vector for the query (no endpoint, or one that does not answer within a second) a query still
needs every word to match. An endpoint that does not answer leaves the lexical order and is retried every minute.

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

`analytics steps` reads `GET /api/analytics/steps[?hours=N]` (168 hours by default, 400 with `history_s` for a window
longer than the telemetry history): one row per model request of the
window, oldest first, that [Connect sources](sources.md#read-each-step-of-a-session) defines. `skill` is the skill
most recently loaded in the session, `none` before any load; `activities` and `keys` hold one entry per tool call
the step made, a key being the command the server's redactor left, else the tool's name; `tokens` is
`{input, output, cache_read, cache_write, reasoning}`.

`analytics transitions` reads `GET /api/analytics/transitions[?hours=N]` and `analytics cells` reads
`GET /api/analytics/cells[?hours=N]`, each with the window and refusals of `analytics steps`. They place a task by its
board labels `kind-<kind>` and `size-<n>`; a task missing either is in neither report, and neither ranks a Codex or Cursor step.

`analytics scores` reads `GET /api/analytics/sessions[?hours=N]` and joins each completed Claude Code task to its merged pull request on `--repo`
(found by `TASK-N` in the title among the 500 most recently updated closed pulls; token from `GITHUB_TOKEN` or `GH_TOKEN`). A task scores
40 clean completion, 20 mid-task operator prompts, 20 commits after the PR was ready, 15 operator rating and 5 time-to-merge; a part that
is missing (no merged PR) drops out and the rest renormalize. Until an operator rating exists, a task that raised its model or effort mid-task
rates 0 and one that lowered it rates 50; an operator rating overrides both. `profile` is the first model and effort of the slice. `off_arm` counts
the row's tasks whose session changed model or effort mid-task.
`verdicts` takes each cell's busiest profile as the baseline and judges every other profile against it: `win` at >=90% posterior probability that its
mean score is within 10 points of the baseline's, `lose` at >=90% that it is lower, else `continue` (also under two tasks on either side, with null
probabilities). The posterior is a normal on the difference of means (Welch standard error); a win outranks a loss.
[Connect sources](sources.md#price-each-transition-and-report-each-cell) defines their columns and what they cannot see.

`analytics graph`, `analytics stages` and `analytics diff` read `GET /api/analytics/graph`, `/stages` and `/diff`, each
with the window and refusals of `analytics steps`, and place a task as `transitions` does.
[Connect sources](sources.md#graph-a-transitions-activities-and-diff-a-fast-run-against-a-slow-one) defines their
columns and what they cannot see.

A move carries the actor that makes it. The machine YAML names, per event, who fires it (`writers`), and each move
the server offers lists them as `writers`; `POST /api/move` takes `{task, to, actor}`; the page sends
`operator`, and a move naming no actor is `anonymous` (`agent` when it names a session), never the operator. The server refuses an actor outside the event's writers before the board
writer is asked, so a move declared for `operator` alone (sending an In Progress task back to Ready) is refused to
`starpulse task move`, which always moves as `agent`. A board adapter's `writer` receives that actor as its third
argument: `writer(task, status, actor)`. `/api/move` is unauthenticated on the LAN, so this stops an agent's
accident, not an adversary.

The same file names, in a `cues:` block, the workflows an event cues: each entry is `{event, dag, on, resolves, grace}`, with
`dag` as `<instance>/<workflow>`, `on` the occasion the page shows (`push to main`) and `resolves` either `forced` (a
failed run stays pinned until a forced rerun) or `next` (it clears on the DAG's next run). `grace` is optional, in seconds, and defaults to 300: a merge whose
cued run has not started that long after it shows `overdue` on the Ledger. The cued event must reach
exactly one state, beside which the page draws the cue; a file with no block has no cues.

`native` and `upstream_backlog` boards load every machine file under `.starpulse/machines/` beside the Board's, not only
the one `[board] machine` names: each other file is a flow named by its file stem, drawn
with the same writer check as the Board's (`refuse_unlisted` against the configured workflows). A file may declare how
the page draws it: `tiers` (state ids per stage), `main_line` (the Board's axis; its lanes in order when absent) and
`rests` (states drawn final though an event leaves them); `submachines` (`{state, machine, exits, routes, when}`, `machine` a sibling's
file stem, `exits` mapping each of its final states to the event of this machine that leaves `state`, and `routes`
mapping a phase state to the event that leaves `state` toward it when the task type's `[sequences]` entry (see
[serving](serving.md)) lists that phase next, the exit's own event otherwise); and
`launches` (per workflow, `{skill, machine}`, `machine` a sibling's stem or absent); and `next` (`{kind, name}`, `kind` `skill` or `operation`, the edge a finished skill hands to, served as `null` when absent: no edge is inferred). The Board is also drawn with every
writer and the `dagActors` among them. A state, event or flow a declaration names that does not exist is refused.

A batch move names `tasks` in place of `task`: one `POST /api/move` with `{tasks, to, actor}` answers each task with its own verdict.

A move may also name the mover's session: `POST /api/move` takes `{task, to, actor, session, harness}`, and
`starpulse task move` sends `--session`, else `STARPULSE_SESSION`, and `--harness`, else `STARPULSE_HARNESS`; the
task `create`, `edit`, `assign`, `archive` and `checkpoint` verbs send the same two. A move that names one calls the writer with it as a fourth argument,
`writer(task, status, actor, session)`; one that names none calls it with three, so a writer written before sessions
keeps working. The writer records the session as the task's assignee when the move is a claim, `BoardTask.assignee`
carries it back, and a `Written.advice` string rides in the move's answer (`advice` in the CLI document, empty when
the writer has none). The native and Backlog.md adapters' writers record the assignee as a `**Assignee:** <session>` line in the
task's notes (a `**Holder:**` line from before the rename is still read), in the same edit as the `In Progress` status, because the Backlog CLI drops a frontmatter key it
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

`poller:pulls` is the pull request poller's liveness. `serve` runs the poller on a thread of the pulls worker and starts
it again after a crash, with a delay that doubles from 1 s to 60 s; while it runs it writes the time to the event log
every 15 s. The check fails when that beat is over 60 s old or was never written, and runs only when the config polls
pull requests (`pull_requests`) and `gh` is installed. Only the server reads the beat, so `starpulse doctor` takes this
check from `GET /api/doctor`.

`GET /api/doctor` serves the contract checks and `poller:pulls` as `{ok, checks: [{check, status, reason}]}`, read from
the server's own snapshot, config and log and held for a minute; the page draws it as the Ledger's doctor banner. A
server with no contract to read answers `{ok: true, checks: []}`.

`skills` reads no server. The package bundles four skills about StarPulse itself: `operating-starpulse-board` (what to
work next, why a task cannot move, moving it), `authoring-starpulse-machines` (machine YAML, writers, guards,
submachines, `machine validate` and `machine import mermaid`), `writing-starpulse-adapters` (the board, machine-events
and runs contracts, the adapter kit, the CloudEvents ingest) and `setting-up-starpulse` (starting the server, config,
`doctor`). It also bundles five task phase skills, each with its phase machine: `starting-task` (find or file the task,
claim it, make its worktree), `tdd` (red, green and refactor cycles, criteria checkpoints, docs), `deliver` (final
gates, commit, push, PR and green checks, or the no-PR finalize), `review-fix` (review threads, conflicts and checks
until the task moves to review) and `mitigate` (stop a failing service's growing impact, recheck its health, and
diagnose only once it is green). They reach a project's own behavior only through StarPulse verbs and
`starpulse command run` with the `start`, `test`, `check`, `deliver`, `pr-status`, `finalize`, `health`, `snapshot` and
`mitigate` commands; a command
the project does not map exits 4, and the skill does that step as the project's `AGENTS.md` says. `skills install`
copies them to `.claude/skills` (`--claude`) or `.agents/skills` (`--codex`) in the working directory, or with `--user`
to `~/.claude/skills` or `~/.agents/skills`. An install records what it wrote, so a copy you edited afterwards is
refused (exit 1) until you pass `--force`, while one the package has since updated is replaced; `skills list` reports
which state each copy is in.

A skill that drives a phase machine names it with a `machine:` key in its front matter, and the machine file sits beside
`SKILL.md` in the skill's directory. An install copies that file with the skill, so the copy carries its machine to the
harness. Before it writes anything, an install refuses a skill whose named machine is missing, and a machine with a State
that declares no `role`; a skill with no `machine:` key installs as before.

Claude Code can load the same skills as a plugin instead of copies: the repository is a plugin marketplace
(`.claude-plugin/`), so `/plugin marketplace add trantor-org/starpulse` then `/plugin install starpulse@starpulse`, or
a `directory` marketplace pointing at a local checkout, serves them as `starpulse:<skill>`, read in place. The plugin
reads each skill's directory where it sits, so the machine beside `SKILL.md` is found at the same path with no install
step.
The `starpulse-board` mod ([trantor-org/starpulse-board](https://github.com/trantor-org/starpulse-board), `/plugin marketplace add trantor-org/starpulse-board`, then `/plugin install starpulse-board@starpulse-board`)
runs `starpulse board --assignee <session id>` when a session starts, after each tool call and after each turn, so a
task claimed mid-turn shows before the turn ends. It draws each task that session holds as one row above the prompt in
StarPulse's palette: lane icon, ID, the title (or the reason a Needs attention task waits on the operator, or what a
Waiting task waits on), a bar of checked acceptance criteria with `k/n`, the lane, and the PR with its check state. A
server that serves no checked state draws the criteria count without a bar. Details opens a pane with the criteria
ticked off, the assignee and the PR; ✕ hides the band until its Show button or `/board`. The Claude Desktop (SSH) row is one
`Svg` and the terminal row is Ink text. Icons are Nerd Font v3 glyphs; the `glyphs` plugin option (`nerd`, the default, or `plain`) sets
the plain Unicode characters instead, for a terminal without a Nerd Font, since a terminal cannot report its font. The band
draws no fill. The Board and Sessions panes' root Box is filled black (`#000000`) down the dock body's rows (`scroll.bodyRows`) to cover the grey the dock paints
behind every pane cell. The dock's tab strip, left border and bottom row are Claude Code's `composerSidebarBackground`, grey in the dark theme; the plugin's
`custom:starpulse-board:black-dock` theme (`themes/black-dock.json`) is the dark theme with that key black. No other element sets a background and every Button is `plain`. The `Svg` pulses the lane dot of an In Progress task and a running check, and
stops under the system's reduced-motion setting; the terminal row does not animate. `/board` lists the tasks with
their titles. It reads only the `starpulse` CLI, retrying `~/.local/bin/starpulse` when the one on `PATH` fails or is missing, so it
shows no tasks when no server answers (`$STARPULSE_URL`, else `http://localhost:8766`).

Below the tasks one button counts every other Claude Code session on the host by status (`2 working · 5 idle`, each with its status icon), from
the registry each session writes under `~/.claude/sessions/`, reread every 5 seconds without waiting on `starpulse
board`. On the first list the dock opens by itself, without the keys, on a fullscreen terminal of 144 columns or more:
the Sessions pane, one row per session with its status, when the list holds a session, then the Board pane, so the
Board is the tab on show. Until the first prompt, the first pane another plugin opens is followed by the Board closing
and reopening, so the Board stays on show. Pressing the count opens Sessions with the keys in the pane. Sessions shows only in the dock: placed inline
(outside the fullscreen layout, or narrower than the dock) it closes itself. The pane lists only the sessions it can
switch to: each one running in a tmux pane (as a StarPulse Start session does, in tmux session `task-<N>`) is a button
that runs `tmux switch-client` to it, and this session is listed too. A background (`claude --bg`) session or one the
desktop app started has no tmux pane and is left out. Switching needs the session showing the pane to run inside a tmux
client; otherwise the press shows a toast.

The pane groups rows as Active and Archived (Archived folded by default); Active holds working and idle sessions
together, told apart by the status icon. Each row draws the status icon, the name, a `you`
marker on this session, the task it holds as a lane-coloured chip, the age and an archive icon. `n` starts a new tmux
session running `claude` in the workspace and switches to it; `f` filters by name, tmux session or task, and the status
chips (working, idle, archived) combine as OR; `a` archives the focused row, killing its tmux session (this session
first starts and switches to a fresh one). Archived sessions persist in the plugin's store and resume with
`claude --resume <id>` in a new tmux session at their recorded directory.

Besides opening at session start, a Board button beside the count, and `/kanban`, open the Board pane with the keys: the
board as a kanban, docked as its own tab and, like Sessions, closing itself when placed inline. Its header names the open-task count beside a refresh
button. It stacks the open lanes (In Progress, Review, Needs attention, Ready, Waiting), each a header with the lane's
icon and colour, its count and a rule, that folds and unfolds the lane; Ready and Waiting start folded. A task is a row of
its ID, its title (or the reason a Needs attention task waits, or what a Waiting task waits on), a four-cell bar of
checked criteria and its PR's check icon; titles truncate first on a narrow dock, then the bar. Each task is a button
that picks it: the row opens to the full title, the assignee, the criteria count, the PR and its checks, and its actions. Start session, on a Ready, Waiting or Needs attention task, posts
`/api/start` with the task's assignee and harness `claude`, then runs `tmux switch-client` to `task-<N>` (outside a tmux
client, a toast names the `tmux attach` command). Go to session, on any other lane, switches to the task assignee's live
session, or toasts that it has none. A `→ <lane>` button, coloured by the target lane, for each move the board lists posts `/api/move`; a refused move
shows the server's reason as a toast and leaves the board as read. While the pane is open it follows `GET /api/lanes?state=<lane>…`
(one `state` per open lane), an event stream like `/api/held`: the server sends the lanes as a `lanes` event on connect and again only
when they change, and the pane redraws from it with no `starpulse` run and no timer. Each held task carries `skill` (`{name, states, current, next}`: the skill machine its phase holds it in, its state ids in order, the state it holds, and its `next` edge; `null` off the In Progress phases) and `interactive` (true once an accepted `POST /api/take-over` flipped it; `false` before). A held or lanes stream wakes only for a change to a task it shows, to a task one of those waits on, or to one that moves into its view, and the streams a change wakes read one build of the columns, so a change costs the board once, not once per open stream. A docked pane that `/kanban` did not open, such as
one left in the dock across `/clear`, starts the stream when it draws. Closing the pane, or placing it inline, ends the
stream; a stream that drops is retried with backoff while the pane stays open. The refresh button still rereads the board once.

## The pull-request store

With `gh` available and the config's `pull_requests` not false, `starpulse worker pulls` (a child `serve` supervises) keeps a store of pull requests (table
`starpulse_pull_requests`) as a projection of the lifecycle events, and polls GitHub for nothing. A task's `machine:events` entry (`PR_OPENED`, `PR_READY`, `PUSHED`, `CHECKS_PASSED`, `CHECKS_FAILED`,
`CONFLICTED`, `MERGEABLE`, `THREADS_CHANGED`, `PR_MERGED`, `PR_CLOSED`) lands on the pull requests the Board says the task cites, and a completed `ci:jobs` entry sets the head commit and its job's result on the
record of the pull request it names. An entry applied twice leaves the record as once did, so the log may be replayed from any point. A close names its pull request in the entry's `repository` and `pr` fields and applies to that one alone, none once the store holds it closed; a close that names none applies only when the task cites a single open pull request.
`POST /api/pulls/refresh` reads one pull request alone from GitHub (one GraphQL query, its `rateLimit` cost logged as `pull requests: <repo> query cost N, remaining N, resets T`) and replaces its record:
the way a pull request no task's events name enters the store, and the way a record gets its head branch, base, merge commit and changed files. The
repositories a refresh may name are those of open tasks' pull request links, the `[[repos]]` entries under a linked owner, and those already stored.
At each start the worker reads every record it holds OPEN the same way, one pull request at a time, so a record whose close no event
reached (one an older listing poll wrote) closes once and the OPEN set matches GitHub's. It reads every MERGED record with no merge
commit too (a lifecycle event wrote it bare), which the `pin-bump` release gate needs to release a task waiting on that pull request.

`GET /api/pulls[?repo=owner/name][&number=N][&state=OPEN|MERGED|CLOSED][&body_contains=text]` serves the store,
`{pulls: [...]}`, ordered by repository then number. Each record holds `repo`, `number`, `state`, `isDraft`,
`mergeable`, `baseRefName`, `headRefOid`, `body`, `checks` (`pass`, `failing`, `pending` or `none`), `requiredChecks`
(`{name, result}`), `threads` (open review threads), `headRefName` (the head branch), `unresolvedThreads`
(`{id, author}`: each open thread's id and its first comment's author login, `null` for a deleted account, among the
first 100 threads), `updatedAt` and `fetchedAt` (epoch seconds of the last event or read that changed the record). `headRefName` and `unresolvedThreads` are
`null` for a record saved before they were kept; its reader asks GitHub. A `number` that is not an
integer or an unknown `state` answers 400.

`GET /metrics` serves Prometheus text:
`starpulse_page_build_info{build="<id>"} 1` names the page build the server holds, the id its `build` event sends, so
a rebuild moves the series; a server whose `static/` holds no build serves none. The same route carries the server
process's own metrics, `process_resident_memory_bytes`, the `process_cpu_seconds_total` counter,
`process_threads`, `process_open_fds` and `process_start_time_seconds`; the last changes on every restart, so a growth rule can tell one
process lifetime from the next. A host with no `/proc` serves none of them.

`waiting_on` is the dependencies neither in the `done` lane (hot or cold) nor settled as completed. `criteria` and `pause_reason` come
from `BoardTask.acceptance_criteria` with `acceptance_checked`, and `BoardTask.pause_reason`; an adapter that sets none
serves `[]` and an empty reason. `prs` are the task's pull
request links, each with the checks, merged state, open review threads and commits behind `main` the server last read
when it has them.

## Importing a board's history

`starpulse import-history FILE [--config starpulse.toml]` adds a board's earlier lane changes to the store the config's
`database_url` names, as `serve` opens it. It is not an agent verb: it reads no server and `help --agent` leaves it out.
`FILE` is JSON Lines, one change per line, and a blank line is skipped:

```json
{"event_id": "ff971697-10ef-4d27-9d71-eb7a45bac3b9", "task": "TASK-1095", "lane": "Done", "time": 1790289615.0}
```

`event_id` names the move and makes it land once, `lane` is the status as its tracker spelled it, and `time` is the
epoch second the task entered it; a field beyond these four is ignored. A change into the lane its task was already in,
or a move (task, lane, time) the store holds under another id, adds nothing. The changes may be older than the rows the
store holds: each row is written unchained, then the store's lane history is repaired and its summaries rebuilt, as a
start does, so each task's path chains in time order. Stop `serve` first: a row it records while the summaries rebuild
is missing from them.

It prints one JSON line: `source`, `store` (the database URL, password hidden), `read` (the change lines in the file),
and `imported` (the changes the store holds afterwards that it did not before, so a second run reports 0). A line that is not a change exits 1 and
names the file and line; a flag the command does not allow, a file or config that cannot be read, or a board the config
does not assemble exits 2.

## Replaying history against the machines

`starpulse conform [--config starpulse.toml] [--since WHEN] [--machine NAME]...` replays the history the config's
`database_url` holds against the machines the project declares and prints each violation. It is not an agent verb: it
reads no server and `help --agent` leaves it out. `WHEN` is an ISO date or epoch seconds; `--machine` limits the replay
to a named machine and may repeat, and a name the project does not declare is a usage error.

The `board` machine is judged on the board's lane changes: a move is a violation when no transition leads from the lane
the task left to the lane it entered, and a task's first lane is judged from the machine's initial state. Every other
machine the feed draws is judged on its `machine:events` entries, each task replayed from the initial state: an event no
transition declares from a state the task may be in is a violation, and the task stays where it was. A task in a final
state may begin again from the initial one.

It prints one JSON line: `machines` (one `{machine, replayed, violations}` per machine with history, where `replayed` is
the moves judged and each violation is `{source, move, count, tasks}` with up to five example tasks), `replayed` and
`violations` (totals). The exit code is 0 when no move is a violation, 1 when one is, and 2 for a flag the command does
not allow, a config that cannot be read, a board the config does not assemble or an unknown `--machine`. Guards are not
judged: the history keeps the lane and the event but no facts, so a move is checked by its shape. [Conformance
violations](serving.md#conformance-violations) counts the same judgment live.

## Backing up the store

`starpulse backup --to DIR [--keep N] [--config starpulse.toml]` writes a `VACUUM INTO` copy of the SQLite store the config
names into `DIR` as `starpulse-<local time>.db`, proves it with `PRAGMA integrity_check`, and keeps the newest `N` copies
(default 14). It prints one JSON line with the copy's path, `integrity` and the `kept` count, and exits 2 for a store that
is not SQLite, which its own backup tool owns. The read lock is held only for the copy, so `serve` keeps answering.

## Reloading a running serve

`starpulse reload [--config starpulse.toml]` makes the `serve` started from that config pick up changed code and config
without a restart of the whole server. It is not an agent verb: it reads no server and `help --agent` leaves it out.
`serve` publishes a loopback endpoint and a random token in `<config stem>.control` (`starpulse.control` for
`starpulse.toml`, `starpulse-other.control` for `starpulse-other.toml`), mode `0600`, beside the config (else `starpulse.control`
in the working directory) and removes the file when it stops; `reload` reads that file, so pass the same `--config`.

`serve` reads each process's import closure from the installed code in a fresh interpreter, as a child started now would
load it: the files of the `starpulse` modules the process imports, with their content hashes. It compares that and the
process's config blocks with the last reading, taken when `serve` started or at the last `reload`, then:

- **replaced**: a child whose closure changed, or whose `database_url`, `board_type` or `board` changed, is ended and
  started again with a new pid. The `runs` child builds its adapters once, so a `runs`
  change also replaces it.
- **reloaded**: a child whose only change is its own config block (`pull_requests`, `repos`, `ci`, `release`,
  `task_actor` for `pulls`; `scheduler`, `level`, `session_start_url` for `scheduler`) keeps its pid and re-reads the
  config on `SIGHUP`. Where the platform has no `SIGHUP`, it is replaced instead.
- **kept**: a child with no change.
- **re-executed**: `serve` replaced itself, in place, because its own closure changed. Every child is ended first, so each
  is `replaced`: the new `serve` starts them again.

A closure that cannot be read, such as a half-written module, or a config that does not load, changes nothing.
So does a machine definition change that drops a State holding live Tasks without a `migrations` mapping; the refusal
names the States and Tasks ([the machine registry](serving.md#machine-registry)).

It prints one JSON object, and the reply is sent before a `serve` that re-executes replaces itself:

```json
{"supervisor": "kept", "children": {"pulls": "kept", "scheduler": "replaced"}}
```

| Exit | Meaning |
| ---- | ------- |
| 0 | The reload ran; the JSON names what each did. |
| 1 | No supervisor is running: no `<config stem>.control` beside the config, or nothing answers on its port. Says so on stderr. |
| 2 | `serve` refused the reload, such as a closure that does not import; the reason is on stderr and nothing changed. |

## Importing a board with its runs

`starpulse import-board [--config starpulse.toml]` moves a board over in one verified import (D11). Each task the
store's lane history names becomes a `TaskImported` of the board's record followed by its recorded lane changes as
imported `Transitioned` Events; each `runs:events` entry becomes an Event of its run's stream. It then replays every
task and compares the row with the board's record. Like `import-history` it is not an agent verb; stop `serve` first.

It prints one JSON line, the verification report: `tasks`, `imported`, `equal`, `differing` (task to the fields whose
replay differs), `gaps`, `reconciled` (tasks whose History fell behind their file, caught up by one `FieldsEdited`), `runs`, `runs_imported` and `verified`. A task whose lane history ends elsewhere than the board,
or that has none, is a gap the earlier writes left: it is imported as the board shows it and listed in `gaps`. The exit
code is 0 when every task is equal, 1 when one differs, and 2 for a config or board that cannot be read. A second run
imports nothing and verifies again. `--dry-run` imports into a scratch store and reports, leaving the real store untouched.
