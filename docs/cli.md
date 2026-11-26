# Agent command line

An agent reads and works the board through `starpulse` verbs, each printing one JSON document.

```sh
starpulse board --milestone launch --label api   # tasks per column, with dependencies, pull requests and moves
starpulse search "signing keys" --limit 5        # tasks holding every word in title, description, criteria, notes or comments, best first
starpulse task show PROJ-45                      # one task: lane, what it waits on, pull requests, moves
starpulse task find --source rotate-key          # the open tasks filed under that source key; none exits 0
starpulse task moves PROJ-45                     # every column it may move to, allowed or refused to the agent
starpulse task move PROJ-45 <state>              # move it as the agent; a refusal is the verdict, exit 1
starpulse task trace PROJ-45 --machine in-progress  # where the task has been: Board lanes, or one machine's events
starpulse task create "Rotate the secret" --priority high --label ops --ac "It rotates"  # open a task; its id
starpulse task edit PROJ-45 --title "Rotate the signing secret" --label ops   # one write, refused whole when stale
starpulse task show PROJ-45 --markdown          # the task rendered as markdown, in `markdown`
starpulse task edit PROJ-45 --editor            # break-glass: edit that rendering in $VISUAL/$EDITOR, import it as events
starpulse task edit PROJ-45 --check-ac 2 --remove-dod 1 --append-notes "Verified."  # items by number, a notes line
starpulse task profile PROJ-45 @agent-standard-high  # route it to an agent profile
starpulse task archive PROJ-45 --reason "superseded"  # archive it from any lane, with the reason as a comment
starpulse task restore PROJ-45                   # return an archived task to the board, unchanged
starpulse task retire PROJ-45                    # take a finished task off the board into the history store
starpulse task retired PROJ-45                   # read a retired task's file name and text back
starpulse task complete PROJ-45                  # move a Done task to the completed tasks
starpulse task reopen PROJ-45 --reason '<why>'  # return a Done task, completed or not, to In Progress
starpulse task checkpoint-ac PROJ-45 2 "pytest exits 0"  # check criterion #2 and record the evidence
starpulse machine show in-progress               # a machine's states, transitions and the tasks now in each
starpulse milestone list                         # every open milestone: title, outcome, specs and ADRs
starpulse milestone add "Launch" --outcome "Shipped" --spec "doc-1 - plan" --adr docs/adr/a.md
starpulse doc create "Plan" --type specification --folder specs --body "# Plan"
starpulse runs list                              # each workflow as <instance>/<workflow> with its latest status
starpulse watch --task PROJ-45                   # one JSON line per change, until you stop it: wait without polling
starpulse snapshot                               # everything the page draws, as one document
starpulse doctor                                 # does this install work: each check passes or fails, with why
starpulse rehearse --config starpulse.toml --database-url copy.sqlite  # start serve on a COPY of the store and wait for /api/health
starpulse skills install --claude        # copy the bundled skills into .claude/skills
starpulse help --agent                           # every verb with its arguments, output keys and exit codes
```

Four verbs work on files; each writes one JSON document the same way:

```sh
starpulse machine validate .starpulse/machines/*.yaml   # schema and compile errors, each with its file and line
starpulse machine import mermaid flow.mmd               # draft a machine file from a stateDiagram-v2 diagram
starpulse config check --config starpulse.toml          # unknown keys by name, and the effective config with defaults
starpulse session records <session-id>                  # a session's transcript records grouped by task, read from the files
```

These verbs read the running server (`starpulse serve`) over HTTP: `--server URL`, else `STARPULSE_URL`, else
`http://localhost:8766`. When that default answers 400 (a TLS server refusing plain http), the verb exits 3 naming
the unset `STARPULSE_URL`. `STARPULSE_TOKEN`, when set, is sent as a bearer token on every request.
These verbs also send `X-StarPulse-Client: cli`, so the server's latency metric labels their caller `cli`; `starpulse event` does not.
Each writes one JSON document to stdout and nothing to stderr, except `watch`, which writes
one JSON line per change; an error is `{"error": "...", "code": "..."}`. The exit code is 0 for success, 1 for a refused or invalid request, a refused move or a failed `doctor` check, 2 for a usage
error, 3 when the server is unreachable (the error names the address tried) or has no board writer and 4 for something not found and 5 when a `command run` child ended pending. A write the server answers `503` with `Retry-After` while it restarts or replays its feed fails with code `unavailable` and a
`retry_after` key (seconds) in the error, for a caller to send it again. A task create or edit that got no answer from a server that may have received it (a timeout, a reset) fails with code `unavailable` and `outcome: "unknown"`: the write may have landed, so read the task before sending it again. A verb
reads the server on every call and keeps nothing, and `help --agent` is generated from the command parser, so it
lists exactly the verbs there are.

| Verb | Arguments | Document |
|---|---|---|
| `snapshot` | | the server's full snapshot, the one verb that reads it whole (`/api/snapshot?view=full`, [Cold done tasks](serving.md#cold-done-tasks)): `graphs`, `flows`, `dags`, `pools`, `pulls`, `claims`, `settled`, ...; each `flows` entry but the Board's also carries `ties` (`{kind, machine, state, dag, when}`: `declared` or `dag`), `parent`, `depth`, `chain`, `nested`, `last` and `stuck` (`{machine, state, since}`, a task idle over 2 h), rolled up from the machines nested below it; `machineStrip` counts the machines entered from the In Progress one ([Machine rows](serving.md#machine-rows)) |
| `board` | `--state`, `--milestone`, `--no-cold`, `--label`, `--profile`, `--assignee`, `--type` | `columns`: each `{state, name, tasks}`; a task is `{id, title, lane, phase, substate, done_at, profile, assignee, milestone, type, labels, dependencies, waiting_on, criteria, pause_reason, readable, source, prs, moves}`, `phase` the state of an `in_progress` task's In Progress machine and `substate` the state of that phase's submachine (null when it has none; only the current phase's submachines count); while a submachine holds the task and the In Progress machine has no state for it, `phase` is the state that submachine is linked to, `done_at` the ISO time a `done` task entered the lane (null otherwise), `profile` the agent profile it is routed to and `assignee` the session that last claimed it (empty when none has), `criteria` each acceptance criterion as `{text, checked}`, `pause_reason` why a `needs_attention` task waits for a person (empty otherwise), `--profile` keeping only tasks routed to that profile, `--assignee` only that session's tasks (`--holder` and a `--assignee` value starting with `@` are the one-release aliases of the old keys) and `--type` only tasks of that type; `--milestone` also lists the milestone's done tasks past their hot day (`/api/done` cards: no `dependencies`, `criteria`, `prs` or `moves`) |
| `search` | `QUERY...`, `--limit`, `--label`, `--finished-within-days`, `--before` | `query` and `hits`: each task holding every word of the query as `{task, title, lane, score, snippet, field}, `field` naming the part that matched (`title`, `description`, `criteria`, `notes`, `comments` or `task`)`, best match first, at most `--limit` (1 to 100, default 10); each `--label` keeps only the tasks carrying it, and `--finished-within-days N` drops a task that finished more than `N` days ago; `--before TASK` keeps only tasks of `TASK`'s prefix with a lower number, applied before `--limit` cuts; a blank query, a limit out of range or a window that is not a positive integer or a `--before` that is no task key exits 1, and a server that keeps no index exits 3 |
| `task show` | `TASK` | a task as above, with its `description`, in which each bare `TASK-N` is a link to the task's card on the Board and each `#N` (three digits or more) a link to the task's pull request of that number, while code spans, existing links and bare URLs stay as written; a task done over 24 h ago is read whole from its board record, lane `done` with its `done_at` and merged `prs` (a settled row reads `archived` only when its file is not Done); a completed or archived task has only its `id` and where it settled as `lane` |
| `task find` | `--source` | `source` and `tasks`: each open task filed under the key as `{id, title, state}`, an empty list when none (exit 0) |
| `task moves` | `TASK` | `task`, `lane` and `moves`: each column the task may move to as `{allowed, reason, skill}`, as the agent meets it |
| `task move` | `TASK...`, `TO`, `--session` | `ok`, `task`, `to`, `reason`, `skill` and `advice`: the move made, or the refusal and the skill that satisfies it (exit 1); exit 3 when the board has no writer. Several tasks move one `PUT /api/tasks/{id}` each, judged on its own: the output is `moved` and `refused`, each refused task with its reason, and a refused task exits 1 while the others stay moved. An agent session that does not hold an In Progress task another session holds is refused, naming the holder; the operator, a workflow and a write naming no session are not |
| `task trace` | `TASK`, `--machine` | `task`, `machine` (null without `--machine`), `path` and `steps`, and with the Board's lane changes `plan_revisions`, the count of `PlanRevised` Events; the Board's `{at, from, to}` lane changes, or with `--machine` that machine's `{at, event, state}`, oldest first; an unknown flow exits 4, a task never seen has an empty `path` |
| `task create` | `TITLE` or `--batch FILE`, `--description`, `--priority`, `--impact`, `--urgency`, `--tier`, `--milestone`, `--profile` (alias `--assignee`), `--status`, `--type`, `--label`, `--dependency`, `--ac`, `--reference`, `--documentation`, `--dod`, `--follows` | `task`: the new id (the next number past every open, completed, archived and retired task); the task is written whole in one write, in the board's first lane or the lane `--status` names, so no second write is needed to finish it and a refused create leaves no task; `--label`, `--dependency`, `--ac`, `--reference`, `--documentation` and `--dod` repeat, the criteria and Definition of Done items numbered in order; a `--documentation` that is an open doc's id (`doc-12`) is stored as that doc's file, and an id no open doc has exits 1; `--follows` records the id of the finished task this one follows up as the task's `follows` field, and a blank value removes it; `--priority`, `--impact` and `--urgency` are each `high`, `medium` or `low` (Impact and Urgency set the task's Priority weight in the scheduler's admission order); `--tier` is `regression`, `bug`, `leverage`, `standard` (a create that names none takes it) or `decide`, and an unknown tier exits 1; a blank title or an unknown priority exits 1; a board that cannot create tasks exits 3; `--batch FILE` (`-` for stdin) takes a JSON list of task specs (`title`, the detail fields, an optional `ref`) and creates them in one request (a board whose `[board]` sets `cohort_milestone = true` refuses a spec with no `milestone` in a batch of two or more, and a lone spec needs none), a spec's dependency `ref:<label>` becoming the new id of the earlier spec with that `ref`; `task` is then the list of new ids, and a refused spec leaves the others created, exits 1 and names each refused spec's position and reason in `refused` |
| `task edit` | `TASK`, `--title`, `--type`, `--priority`, `--tier`, `--profile` (alias `--assignee`), `--milestone`, `--label`, `--dependency`, `--reference`, `--documentation`, `--follows`, `--modified-file`, `--description`, `--plan`, `--reason`, `--notes`, `--append-notes`, `--final-summary`, `--ac`, `--reword-ac`, `--remove-ac`, `--check-ac`, `--uncheck-ac`, `--dod`, `--reword-dod`, `--remove-dod`, `--check-dod`, `--uncheck-dod`, `--comment`, `--base` | `task` and `changed`, the fields whose value differs, in the record's field names (`labels`, `modifiedFiles`, `finalSummary`); every field given is written in one write, or none: `--base` is a JSON object of the values the caller read, else the task is read at the call, and the edit is refused whole (exit 1, the error naming the stale fields) when any field it changes no longer has its base value; a list flag given at all replaces that whole list, a blank value clears the field, and a change that changes nothing writes nothing, except that a non-blank `--comment` is still written and `changed` is `[]`; `--ac` and `--dod` add an unchecked item, `--reword-ac N:TEXT` and `--reword-dod N:TEXT` replace the wording of item `#N`, and `--remove-*`, `--check-*` and `--uncheck-*` take an item's number as the task shows it before the edit, each repeatable and applied to the list as read (a removal renumbers the items from 1; a number the task lacks exits 1 and writes nothing, a reword with no `N:` exits 2); `--append-notes` adds a line to the end of the Implementation Notes whatever they hold when the write lands, leaves the text before it as written, is not checked against `--base`, and reports as `notes`; `--reason TEXT` says why `--plan` rewrites the plan: once the task is past the unstarted lanes (the Board's initial, ready and waiting) a `--plan` that replaces an existing, different plan is refused without it, and with it appends a numbered `PlanRevised` Event (`ordinal`, `reason`); the first plan of a started task and any plan written while unstarted record nothing, `--reason` without `--plan` exits 2, and it is not checked against `--base`; naming no field (a lone non-blank `--comment` counts) or a `--base` that is no JSON object exits 2, a blank title exits 1, an unknown task exits 4, a board that cannot read or edit tasks exits 3 |
| `task archive` | `TASK...`, `--reason` | `archived`: each task named, archived by one `DELETE /api/tasks/{id}` each; from an agent session an open task only gets the comment `Archive requested: <reason>` and the task actor moves it, so `archived` means requested there, a key the board refuses leaving the others archived and the verb refused (exit 1) with `archived` and `refused`, each refused key with its reason; a non-blank `--reason` recorded on it as the comment `Archived: <reason>`; each open (not Done) task that lists it as a dependency has that dependency removed with a comment saying why, a Waiting one left with no dependency and no Start Criteria moves to Ready, and the output names them; an unknown task exits 4, a board that does not archive tasks exits 3 |
| `task restore` | `TASK` | `task`: the archived task's file moved back to the board's tasks, byte for byte; a task whose number is already open, whose file name is taken or that is not archived exits 1, a retired task is returned the same way; a board that does not restore tasks exits 3 |
| `task retire` | `TASK` | `task`: a finished task (Done, in the completed tasks or archived) taken off the board into the server's history store, its file kept byte for byte under its name, so the board's reads and numbering scan fewer files while a new task still numbers past it and a transition rule's dependency on it keeps the state it was retired in; an open or unknown task, a number already kept with other text, or a board not yet started on its store exits 1 and keeps the file; a board that does not retire tasks exits 3 |
| `task retired` | `TASK` (optional) | `tasks`: every retired task, or the one `TASK` names (matched ignoring case), each `{task, name, text}` with its file name and text; an unretired task gives `[]`; a board that keeps no retired tasks exits 3 |
| `task cold-done` | none | `tasks`: every Done task past its hot day, newest first, each card from `/api/done`, paged until the server has no more; exit 3 when the server cannot list them |
| `task complete` | `TASK` | `task`: a Done task moved to the board's completed tasks, where it is still read and edited; a task that is not Done (or already completed) is refused with the board's reason and skill (exit 1), an unknown task exits 4, a board that does not complete tasks exits 3 |
| `task reopen` | `TASK` | `task`: a Done task, in the board's tasks or its completed ones, returned to In Progress with `--reason` as a `Reopened from Done:` comment written by the task actor; a task that is not Done, or one a merged pull request cites, is refused with the reason (exit 1), a board that does not reopen tasks exits 3 |
| `task dispatch` | `TASK`, `--session`, `--harness`, `--replaces` | `ok`, `task`, `session`, `reason` and `skill`: `PUT /api/tasks/{id}` with `changes.assignee` (and `base.assignee` for `--replaces`) publishes `SESSION_DISPATCHED` for the session (an opaque string; `--session`, else `STARPULSE_SESSION`, required) and the task; the task actor pins it as the task's `assignee` and moves a Ready or Needs attention task to In Progress, and the lane moves only then. `--replaces` names a dead holder whose lease ends first. A task another session holds, a session already holding another In Progress task, or a task outside Ready, Needs attention and In Progress is refused with the holder or task named (exit 1) and nothing published; an unknown task exits 4, a board that cannot dispatch exits 3 |
| `task park` | `TASK`, one of `--until-task TASK` or `TASK#K` (repeatable), `--until SUBJECT` (repeatable event subject) and `--operator REASON`, and `--comment` | `ok`, `task`, `to`, `reason` and `skill`: the task asked to pause for exactly one typed reason, which writes its gate and a request comment and no lane (`to` names the lane the task actor is asked to move it to): `--until-task` adds the named tasks to its dependencies (`TASK#K` also records that it needs only criterion K of that task, and is refused when K is absent or already checked) and `--until` replaces the events it waits on (each an alert or deploy subject, `starpulse.<board>.alert.<rule>.<event>` or `starpulse.<board>.deploy.<component>.<event>`, written as a `kind: event` start criterion), the task actor moves it to `waiting` on the request (`Wait requested:` for `--until`, the dependency for `--until-task`) and releases it on the first of those events, or at once when that event is the latest its run recorded; `--operator` writes an `Ask requested:` comment, and the task actor moves it to `needs_attention` with the reason as its pause reason. No reason or more than one exits 2; a named task that is already Done or is the task itself, subjects on a task that already waits on a task, or a list that is empty, not strings or not alert or deploy subjects is refused (exit 1) with nothing written; an unknown task exits 4, a board that cannot edit tasks exits 3 |
| `task checkpoint-ac` | `TASK`, `CRITERION`, `EVIDENCE` | `task`, `criterion` and `changed` (`["acceptanceCriteria"]`, or empty when the criterion was already checked): the criterion `#CRITERION` checked and the comment `Verified AC #N: <evidence>` appended in one write, with the refusals of `task edit` (a session that does not hold the task may check a criterion; the write names it in a comment); a criterion the task lacks exits 1 and writes nothing, blank evidence exits 2, an unknown task exits 4, a board that cannot read or edit tasks exits 3 |
| `task edit --editor` | `TASK` | `task` and `changed`: opens the task rendered as markdown (the same rendering as `task show --markdown`) in `$VISUAL`, else `$EDITOR`, else `vi`, and imports what the operator changed as the events of an edit, by actor `operator` with writer `break-glass`; an edit that removes or adds a section or field line the rendering cannot map back, or changes `Status` (a move is not an edit), is refused naming it with code `refused` and writes nothing; no change writes nothing |
| `task profile` | `TASK`, `PROFILE` | `task`, `profile` and `changed` (`["profile"]`, or empty when the profile already is that value): the edit of the profile alone, with the refusals of `task edit`; a blank profile clears it |
| `machine list` | | `machines`: each `{name, states, tasks}` with its state ids and its live task count |
| `machine show` | `NAME`, `--format json\|dot` | `name`, `states` (each `{id, name, initial, final, count, tasks}`), `transitions` (each `{source, target, event}` and the `cite` its YAML gives), and the `submachines`, `launches` and `writers` the machine declares; `--format dot` adds `format` and `diagram`, the machine as Graphviz DOT source; an unknown machine exits 4 and names those drawn |
| `machine lanes` | `--config` | `lanes` and `aliases`, offline: the config's `board.machine` file read, `lanes` every non-initial state's `label` (its id when it declares none) in the machine's order, `aliases` each name a state's `aliases` retires, by the lane it became (`{"Blocked": "Waiting"}`); a config with no `board.machine` exits 2, an unreadable machine 1 |
| `machine validate` | `PATH...` | `ok` and `machines`: each `{path, ok, errors}`, an error `{file, line, message}` (`line` is null when the compiler cannot place it); exit 1 when any file is refused. A guard or action name is taken as the adapter's to register |
| `machine import mermaid` | `SOURCE`, `--out` | `written`: the new file, by default `.starpulse/machines/<name>.yaml`; an existing file is refused (exit 1), a missing source is exit 4 |
| `pull show` | `PULL` (`owner/name#N` or a GitHub pull request URL) | one stored pull request as `repo`, `number`, `state`, `isDraft`, `mergeable`, `baseRefName`, `headRefOid`, `body`, `checks`, `requiredChecks`, `threads`, `unresolvedThreads`, `headRefName`, `updatedAt`, `mergedAt`, `mergeSha`, `fetchedAt` and `files` (the changed paths, `null` when unknown), read from the PR store and never GitHub; a citation it cannot read exits 2, a pull request the store lacks exits 4 |
| `milestone list` | `--json` | `milestones`: each open milestone as `{id, title, outcome, specs, adrs, retro, description}`, by ascending number; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no milestones exits 3 |
| `milestone show` | `MILESTONE` | one milestone's record as above; one that is not open exits 4 |
| `milestone add` | `TITLE`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone`: the new id (the next number past every open and archived milestone); `--spec` and `--adr` repeat; a blank title exits 1 |
| `milestone edit` | `MILESTONE`, `--title`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone` and `changed`, the fields whose value differs; `--spec` or `--adr` given at all replaces that whole list, and a change that changes nothing writes nothing; naming no field exits 2, a refused change exits 1, an unknown milestone exits 4 |
| `milestone archive` | `MILESTONE` | `milestone`: moves the file to `archive/milestones/`; refusals as `milestone edit` |
| `doc show` | `DOC`, `--json` | one doc's record as above plus its `body`, the text after its front matter; one that is not open exits 4 |
| `doc create` | `TITLE`, `--type`, `--folder`, `--body`, `--task` | `doc`: the new id (the next number past every open and archived doc); with `--task`, also `task` and `changed`, the doc's file added to that task's documentation in one edit; `--type` is `specification`, `guide`, `readme` or `other` (the default), `--folder` a folder of plain names under `docs/` such as `specs`; a blank title, an unknown type or a folder that leaves `docs/` exits 1 |
| `doc update` | `DOC`, `--title`, `--type`, `--body` | `doc` and `changed`, the fields whose value differs; a change that changes nothing writes nothing, naming no field exits 2, a refused change exits 1, an unknown doc exits 4 |
| `doc archive` | `DOC` | `doc`: moves the file to `archive/docs/`; refusals as `doc update` |
| `doc restore` | `DOC`, `--folder` | `doc`: moves the archived file back under `docs/`, byte for byte, into `--folder` (a folder of plain names such as `specs`; `docs/` itself by default); a doc that is already open, a destination that exists, an unarchived id or a folder that leaves `docs/` exits 1, a board that does not restore docs exits 3 |
| `runs list` | | `runs`: each workflow as `{workflow, status, raw, run_id, started_at, finished_at}` with `workflow` `<instance>/<workflow>`, and `error`, the runs adapters' error or null |
| `watch` | `--machine`, `--task` | one line per change after the connect snapshot, `{event, data}` with `event` `task`, `move`, `pulls`, `claim` or `dags` and `data` the server's delta; `--machine` keeps that machine's changes (`board` takes `task`, `pulls` and `claim`), `--task` that task's, and either drops `dags`; an unknown machine exits 4, the server ending the stream exits 3, and an interrupt exits 0 |
| `command run` | `NAME`, `--task`, `--arg NAME=VALUE`, `--config`, `-- ARGS` | `name`, `argv`, `exit`, `seconds`, `ok` and `pending` (the child exited its declared pending code): runs the argv `[project.commands]` maps `NAME` to, offline, in this directory, with no shell, its output on stderr. Exit 0 when the child succeeds, 1 when it fails (its code is in `exit`), 5 when it exits the code `[project.pending]` declares for `NAME` (`deliver` declares 4), so a pending delivery is never read as a failure, 2 when a placeholder has no value or an element has a brace that is not a placeholder (write a literal brace as `{{` or `}}`), 3 when `argv[0]` cannot run, 4 when `NAME` has no entry, with `"fallback": "AGENTS.md"` |
| `command show` | `NAME`, `--config` | `name`, `argv`, `args`, `invocation` and `pr_body_template`: what `command run NAME` needs, offline: the `--arg` names its argv holds, the call to make, and for an argv with `{body}` the project's pull request template (`path`, `text`), else `null`; an unmapped `NAME` exits 4 with the `fallback` |
| `config check` | `--config` | `ok`, `file`, `unknown_keys`, `errors` and `config`, the effective config with every default filled in (null when it does not load); exit 1 when it does not load (a malformed `[project.commands]` entry included), or when a built-in board's machine names a writer workflow no `[[runs]]` domain lists, which `serve` refuses to start on |
| `doctor` | `--config` | `ok` and `checks`: each `{check, status, reason}`, `status` `pass`, `warn` or `fail`; exit 1 when any fails, never for a warning |
| `session records` | `SESSION`, `--transcripts`, `--config` | `session`, `records` (the count) and `groups`, each `{task, records}` in the order the tasks are first named, `task` null for a session that names none; the records are the transcript's own JSON lines, read from `<transcripts>/<project>/<session>.jsonl` (`--transcripts`, else `[board] transcripts`, else `~/.claude/projects`) and never stored; a task is claimed by a branch the key scheme names or by a shell command or `Skill` call a `claims` pattern matches, and the records before the first claim join the first task; offline; exit 4 when no transcript of the session exists, 1 when the config does not load |
| `skills list` | `--user` | `scope` and `skills`: each `{name, description, claude}`, the harness `absent`, `installed`, `outdated` or `modified` |
| `skills install` | `--claude`, `--user`, `--force` | `scope` and `installed`: each `{harness, skill, path, was}`; exit 1 when a copy was modified since install |
| `help --agent` | | `exit_codes` and `verbs` |

`search` reads `GET /api/search?q=QUERY[&limit=N][&label=L]...[&finished_within_days=N][&before=TASK]`: the words of `q` are each a quoted phrase and all must match, so
punctuation (`PROJ-45`, `NEAR`, `title:`) is text and never query syntax. A task is searchable by its key, title,
description, acceptance criteria, notes and comments, and a match in the title
ranks above one in the description, which ranks above one in a criterion, a note or a comment; words are matched by their
stem (`rotation` finds `rotate`). `score` is higher for a better match, `lane` is the lane the task is in now (or
`completed` or `archived` once it settled) and `snippet` is the text around the match in the part `field` names, the first of title, description, criteria, notes, comments to hold a query word. The index is a SQLite FTS5
table in the instance's own database, filled from the board on the first read, so every adapter is searched the same way, and kept current as each task is placed, edited, moved or retracted; a
task placed again unchanged, as every task is on a restart, writes nothing. A SQLite built without FTS5 serves none: the route answers 404 and the verb exits 3.

Without filters a search reaches every task, open or settled, of any age. Each `label` (repeatable) keeps only the
tasks carrying that label, matched whole (`disk` does not match `disk-usage`). `finished_within_days=N` keeps every
open task and drops one that finished more than `N` days ago: a completed or archived task finished when it settled
(a settled task the board gives no time for counts as older than any window), and a task in the done lane when it
entered that lane (when the lane history does not date that entry, the first time the index saw it there). A task
keeps its earliest finish time until it reopens, so a restart moves none later. `before=TASK` keeps only the tasks
of `TASK`'s prefix with a lower number, so `before=PROJ-11` keeps `PROJ-9` and not `PROJ-SUB-3`. All narrow the lexical and the vector hits alike. The index keeps each task's labels and finish
time beside its text, outside the text's digest, so an index written before them gains them as each task is next
placed, as every task is on a restart, without embedding anything again.

The `[search]` table's `embeddings_url` is optional ([Config file](serving.md#config-file)). Unset, ranking is the
lexical order above and nothing calls out. Set, `serve` sends each task's title and description to that
OpenAI-compatible endpoint in the background, one task to a request so a query never waits behind a batch, and keeps one vector per task and `model`; a query whose vector is held (the last 256 queries are kept)
has its lexical hits (up to the 50 best) ordered by half their bm25 score, relative to the best hit's, and half the cosine similarity of
their vector to the query's, so `score` is that blend. A task whose vector is not stored yet counts as no similarity.
A task that holds none of the query's words is a hit too when the cosine similarity of its vector to the query's is at
least 0.55, so a reworded description still finds the task it rewords; its `snippet` is the task's opening and its
`score` is half that similarity. The server holds the unit vectors as one matrix and scores them in a single product, reading again only the vectors
of tasks a write changed, so a search over thousands of tasks takes milliseconds and never waits for a write. Without a vector for the query (no endpoint, or one that does not answer within a second) a query still
needs every word to match. An endpoint that does not answer leaves the lexical order and is retried every minute.

A search never waits for the endpoint: a query whose vector is not held is answered by the lexical order at once and
embedded in the background (at most 4 at a time), so its repeat is blended. `starpulse search --similar QUERY` and
`GET /api/search/similar` take the same query and answer the same body but wait to embed a new query, for a caller
that needs the meaning ranking on its first ask.

A move carries the actor that makes it. The machine YAML names, per event, who fires it (`writers`), and each move
the server offers lists them as `writers`; a move is a `PUT /api/tasks/{id}` with `changes.status`, over the `base` status the mover read, and `actor`; the page sends
`operator` on a `PUT /api/tasks/{id}` status change, which the server records as a `Move requested: <lane>` comment for the task actor to carry out, and a move naming no actor is `anonymous` (`agent` when it names a session), never the operator. The server refuses an actor outside the event's writers before the board
writer is asked, so a move declared for `operator` alone (moving a started task to Ready) is refused to
`starpulse task move`, which always moves as `agent`. The board's `writer` receives that actor as its third
argument: `writer(task, status, actor)`. `PUT /api/tasks/{id}` is unauthenticated on the LAN, so this stops an agent's
accident, not an adversary.

The same file names, in a `cues:` block, the workflows an event cues: each entry is `{event, dag, on, resolves, grace}`, with
`dag` as `<instance>/<workflow>`, `on` the occasion the page shows (`push to main`) and `resolves` either `forced` (a
failed run stays pinned until a forced rerun) or `next` (it clears on the DAG's next run). `grace` is optional, in seconds, and defaults to 300: a merge whose
cued run has not started that long after it shows `overdue` on the Ledger. The cued event must reach
exactly one state, beside which the page draws the cue; a file with no block has no cues.

The `native` board loads every machine file under `.starpulse/machines/` beside the Board's, not only
the one `[board] machine` names: each other file is a flow named by its file stem, drawn
with the same writer check as the Board's (`refuse_unlisted` against the configured workflows). A file may declare how
the page draws it: `tiers` (state ids per stage), `main_line` (the Board's axis; its lanes in order when absent) and
`rests` (states drawn final though an event leaves them); `submachines` (`{state, machine, skill, exits, routes, when}`, `skill` the skill a session runs while the inner machine does, which the Kanban card and the Star Map branch use as their label, or the machine's own name when `skill` is absent; `machine` a sibling's
file stem, `exits` mapping each of its final states to the event of this machine that leaves `state`, and `routes`
mapping a phase state to the event that leaves `state` toward it when the task type's `[sequences]` entry (see
[serving](serving.md)) lists that phase next, the exit's own event otherwise); and
`launches` (per workflow, `{skill, machine}`, `machine` a sibling's stem or absent); and `next` (`{kind, name}`, `kind` `skill` or `operation`, the edge a finished skill hands to, served as `null` when absent: no edge is inferred). The Board is also drawn with every
writer and the `dagActors` among them. A state, event or flow a declaration names that does not exist is refused.

A batch move is one write per task, each answered with its own verdict.

A move may also name the mover's session: `PUT /api/tasks/{id}` takes `{base, changes, actor, session, harness}`, and
`starpulse task move` sends `--session`, else `STARPULSE_SESSION`, and `--harness`, else `STARPULSE_HARNESS`; the
task `create`, `edit`, `assign`, `archive` and `checkpoint` verbs send the same two. The writer is called
`writer(task, status, actor)`: a move never makes its session the holder. Only the task actor pins a session, from the
`SESSION_DISPATCHED` event `PUT /api/tasks/{id}` publishes for an `assignee` change, and clears it on the harness session-end event. `BoardTask.assignee`
carries it back, and a `Written.advice` string rides in the write's answer (`advice` in the CLI document, empty when
the writer has none). The native adapter's writer records the assignee as the task's frontmatter `assignee` (the harness session-end event removes it) and adds no line to its notes.

`doctor` runs every check even when one fails, so one call names every fault. The checks: `config` (the config file
loads), `server` (it answers `/api/snapshot`), `adapter:board` and one `adapter:<name>` per `[[runs]]` instance (it is
producing: the Board is read, the instance lists workflows and reports no error).

Two contract checks read the config against the machines' cues. `cue:<instance>/<workflow>` runs once per cued
workflow: it fails when no instance lists the workflow or when a `[runs.commit]` key (`after`, `before`, `force`,
`task`) names a parameter the workflow does not declare (read from the runs adapter's declared parameters), and it warns, without failing
the run, when the instance has no `after` key, so its runs pair with a merge only by the time they started.
`repo:<name>` runs once per `[[repos]]` entry and fails when its `path` is not a submodule of the repository `doctor`
runs in. Neither runs while the config or the server cannot be read.

`GET /api/doctor` serves the contract checks as `{ok, checks: [{check, status, reason}]}`, read from
the server's own snapshot, config and log and held for a minute; the page draws it as the Ledger's doctor banner. A
server with no contract to read answers `{ok: true, checks: []}`.

`GET /api/health` answers 200 when the server can serve the board and 503 when it cannot, with the same body:
`{ready, components: {<name>: {ready, detail}}}`. The components are `store` (the event log opened at the schema head; a store a deploy's migrate moved ahead since stays ready),
`board` (the Board is assembled), `writer` (the Board context, which dates the lanes and sweeps the claims, has started) and
`contexts` (every other supervised context has started in this boot). `doctor` adds a `ready` check that fails naming
each component that is not ready.

`rehearse --config <c> --database-url <copy>` is the dress rehearsal of a release: it migrates the COPY, starts
`serve` on it on a free loopback port below the ephemeral range, polls `/api/health` and stops the server. It exits 0 when the server was
ready within `--budget` seconds (default 120) and 1 otherwise, printing the unready components and the end of the
server's log. The server runs with `STARPULSE_REHEARSE` set: the config drops its TLS, telemetry, session start,
tokens, take-over command, producers and `[bridge]` (no `nats` child) and polls no pull requests, only the `board`, `flow-metrics` and `signal-folds` contexts run
(none polls a service, starts a run or session, or listens on a port), pruned rows go to a scratch directory, and no
control endpoint is published beside the config. A Board that does not assemble against the copy (a lane mismatch)
fails the rehearsal.

`skills` reads no server. The package bundles four skills about StarPulse itself: `operating-starpulse-board` (what to
work next, why a task cannot move, moving it), `authoring-starpulse-machines` (machine YAML, writers, guards,
submachines, `machine validate` and `machine import mermaid`), `writing-starpulse-adapters` (the board, machine-events
and runs contracts, the adapter kit, the CloudEvents ingest) and `setting-up-starpulse` (starting the server, config,
`doctor`). It also bundles two task phase skills, each with its phase machine: `fix-checks` (read a red check's log, fix a branch
fault through delivery, or park on the owner of a base or flaky fault) and `mitigate` (stop a failing service's growing
impact, recheck its health, and diagnose only once it is green). They reach a project's own behavior only through StarPulse verbs and
`starpulse command run` with the `start`, `test`, `check`, `deliver`, `pr-status`, `check-logs`, `health`, `snapshot` and
`mitigate` commands; a command
the project does not map exits 4, and the skill does that step as the project's `AGENTS.md` says. `starpulse command show NAME` reads the same table without running it: it prints the `--arg` names the command's argv needs and, for a command with a `{body}`, the project's pull request template (the first of `.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `docs/pull_request_template.md`, `pull_request_template.md` beside the config), so a delivery skill's body keeps the project's sections on the first attempt. `skills install`
copies them to `.claude/skills` (`--claude`) in the working directory, or with `--user`
to `~/.claude/skills`. An install records what it wrote, so a copy you edited afterwards is
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
task dispatched mid-turn shows before the turn ends. `--assignee` and `/api/held` match a session by any name a dispatch can carry: its local Claude id, its bridge id (`session_x`, `cse_x`) or its Remote Control URL, the bridge the session's transcript names under `[board] transcripts`. It opens no pane: the band above the prompt is the whole mod, in the
terminal and in Claude Desktop. It draws the held task's lane icon, ID, title (or the reason a Needs attention task waits
on the operator, or what a Waiting task waits on), a bar with one segment per checked acceptance criterion and `k/n`, the
delivery phases and substates the board serves, the pull request's checks, threads and freshness, and the session's cost,
turns and tokens, in StarPulse's palette. A server that serves no checked state draws the criteria count without a bar.
The head row carries a fold arrow, and on Desktop the PR number as a link; with no held task the band stays on and says
so. The terminal draws the same facts in cells. Icons are Nerd Font v3 glyphs; the `glyphs` plugin option (`nerd`, the default, or `plain`) sets
the plain Unicode characters instead, for a terminal without a Nerd Font. `/board` lists the held tasks with
their titles. It reads only the `starpulse` CLI, retrying `~/.local/bin/starpulse` when the one on `PATH` fails or is missing, so it
shows no tasks when no server answers (`$STARPULSE_URL`, else `http://localhost:8766`).

The band starts, switches to and focuses no session, so it names no multiplexer: a session starts through the board's
Start button (`POST /api/start`), which reaches the scheduler's starter (`session_start_url`, else the built-in tmux
starter; see [serving.md](serving.md)), and the task modal names the claiming session by its Claude session id and link. A fleet on
another multiplexer (herdr) therefore changes nothing here.

The server streams the same facts to a mod: `GET /api/lanes?state=<lane>…` (one `state` per open lane) and `/api/held` are
event streams. The server sends the lanes as a `lanes` event on connect and again only
when they change. Each held task carries `skill` (`{name, states, current, next}`: the skill machine its phase holds it in, its state ids in order, the state it holds, and its `next` edge; `null` off the In Progress phases) and `interactive` (true once an accepted `PUT /api/tasks/{id}` with `interactive: true` flipped it; `false` before). A held or lanes stream wakes only for a change to a task it shows, to a task one of those waits on, or to one that moves into its view, and the streams a change wakes read one build of the columns, so a change costs the board once, not once per open stream.

## The pull-request store

With the config's `pull_requests` not false, the pulls context (a thread of the `contexts` child `serve` supervises, or `starpulse worker pulls`) keeps a store of pull requests (table
`starpulse_pull_requests`) as a projection of the lifecycle events, and polls GitHub for nothing. A task's `machine:events` entry (`PR_OPENED`, `PR_READY`, `PUSHED`, `CHECKS_PASSED`, `CHECKS_FAILED`,
`CONFLICTED`, `MERGEABLE`, `THREADS_CHANGED`, `PR_MERGED`, `PR_CLOSED`) lands on the pull requests the Board says the task cites, and a completed `ci:jobs` entry sets the head commit and its job's result on the
record of the pull request it names. An entry applied twice leaves the record as once did, so the log may be replayed from any point: a start on a store that holds records replays only the entries appended after the cursor the replay keeps in the `pulls.cursor` worker state, a start on a new or wiped store replays every entry the log retains, and a second reader per stream, taken before the replay, hands over each entry appended meanwhile, so a `PR_MERGED` published during a restart is applied without waiting for the replay to end. A close names its pull request in the entry's `repository` and `pr` fields and applies to that one alone, none once the store holds it closed; a close that names none applies only when the task cites a single open pull request.
A pull request no task's events name enters the store from a webhook delivery, which also sets its head branch, base, merge commit and changed files. No endpoint reads a pull request from GitHub on request: the `refresh_token_env` setting is gone, and a config that sets the key is refused.

The store is read through GraphQL at `POST /graphql`, never from GitHub: `task(id) { prs { ... } }` serves the records of the pull
requests a task cites, and `pull(repo, number) { ... }` serves one record whatever task cites it, `null` when the store holds none.
Each record holds `repo`, `number`, `state`, `isDraft`, `mergeable`, `baseRefName`, `headRefOid`, `body`, `checks` (`pass`,
`failing`, `pending` or `none`), `requiredChecks` (`{name, result}`), `threads` (open review threads), `headRefName` (the head
branch), `unresolvedThreads` (`{id, author}`: each open thread's id and its first comment's author login, `null` for a deleted
account, among the first 100 threads), `updatedAt` and `fetchedAt` (epoch seconds of the last event or read that changed the
record), and `files` (the changed paths, first 100; `null` for a record saved before they were kept).

`GET /metrics` serves Prometheus text:
`starpulse_page_build_info{build="<id>"} 1` names the page build the server holds, the id its `build` event sends, so
a rebuild moves the series; a server whose `static/` holds no build serves none. The same route carries the server
process's own metrics, `process_resident_memory_bytes`, the `process_cpu_seconds_total` counter,
`process_threads`, `process_open_fds` and `process_start_time_seconds`; the last changes on every restart, so a growth rule can tell one
process lifetime from the next. A host with no `/proc` serves only `process_threads`. `starpulse_open_pulls{repo}` counts the open pull requests the PR store holds in each repository.

`waiting_on` is the dependencies neither in the `done` lane (hot, cold or retired) nor settled as completed. `criteria` and `pause_reason` come
from `BoardTask.acceptance_criteria` with `acceptance_checked`, and `BoardTask.pause_reason`; an adapter that sets none
serves `[]` and an empty reason. `readable` is the board's `readable` guard verdict on the description, empty when it reads well. `source` is the key the producer filed the task under (`task create --source`), empty when it has none; a client finds an open task by it with `task find --source`. `task create --source` returns the open task already filed under that key, with `existing` true, and writes nothing. `prs` are the task's pull
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

## Showing the board policy

`starpulse policy show [--config starpulse.toml]` prints the board policy that governs, as one JSON line. It is not an agent
verb: it reads no server and `help --agent` leaves it out. The store holds the policy in eight `starpulse_policy_*`
tables (`lanes`, `routes`, `exits`, `watches`, `rules`, `vocabularies`, `profiles`, `tools`), created by the
schema chain and empty until a migration fills them. `source` is `database` when any of them holds a row, else `files`:
the policy then comes from the board machine (`states`, `events`, `writers`) and the `[board]` settings (`guards`,
`types`, `default_profiles`) the config names. The other keys are those eight lists, each row with the columns of its table
(a `lanes` row is `{name, role, position, skill}`). The exit code is 0 once printed, 1 for a store not at the schema head
(run `starpulse migrate`) and 2 for a flag the command does not allow or a config that cannot be read.

## Exporting and importing machines and policy

The store is the source of the machines and the policy; files are an optional copy. None of these verbs reads a server.

- `starpulse machines import [PATH ...] [--config starpulse.toml]` activates each `PATH` (default the Board's `[board] machine` file and each file in `.starpulse/machines/`) as its machine's active version and prints `<name> <hash>` per machine. A first install runs it after `starpulse migrate`. Exit 3: the registry refused a file (reason on stderr; the files before it stay in, those after it are not read). Exit 4: the Board machine would strand live Tasks; the other files are in and the active Board version stays.
- `starpulse machines export [--out DIR] [--config starpulse.toml]` writes each active machine as `<name>.yaml` under `DIR` (default `.starpulse/machines/`) and prints one path per line. Importing the export into a fresh store gives the same active set.
- `starpulse policy export [--out FILE]` writes the governing policy (the store's, else the files') as one JSON document, to stdout by default; `starpulse policy import FILE` makes it the store's active policy and prints its hash. Exit 2: the file is not a policy document.

## Revising the board policy

`starpulse policy revision [--config starpulse.toml] [-m MESSAGE]` writes the data migration that brings the store to the
policy the operator declares. The operator declares a `starpulse.board.model.policy.Policy` (frozen dataclasses: `Lane`,
`Route`, `Exit`, `Watch`, `PolicyRule`, `Vocabulary`, `Profile`, `LaneTool`) in a Python file and names it in the config:

```toml
[board.policy]
declared = "policy/declared.py:POLICY"   # the file, and the Policy or zero-argument function in it (default POLICY)
migrations = "policy/migrations"         # the operator's Alembic chain; created on the first run
version_table = "starpulse_operator_policy_version"   # optional; this is the default
```

The chain is a second Alembic chain beside StarPulse's, versioned in its own table. Each migration carries `CHANGES`: for every
table whose rows differ, the rows added, the rows removed, and for each changed row its key and only the columns that differ
(old and new values), so a one-rule edit writes a migration of tens of lines. Its `upgrade` and `downgrade` apply those rows by
key, a second run leaves the same rows, and a downgrade restores the prior policy. A row is identified by these columns:

| Table | Key |
| --- | --- |
| `lanes` | `name` |
| `routes` | `event`, `source`, `target` |
| `exits` | `event`, `actor`, `trigger` |
| `watches` | `lane`, `fact` |
| `rules` | `position` (declare positions explicitly; inserting a rule mid-list renumbers the later ones) |
| `vocabularies` | `name`, `value` |
| `profiles` | `kind`, `size` |
| `tools` | `lane`, `tool` |

A table falls back to `{"before": [...], "after": [...]}`, the whole table on each side (the form older migrations hold, which
stay readable), when a key repeats in it or the keyed rows would not rebuild a side in order: `routes` and `exits` are read in
insert order, so only rows appended at the end, edited in place or removed from the end stay keyed. The chain's head therefore records the policy The chain's head therefore records the policy
the store should hold. The first run scaffolds the chain's `env.py` and an `alembic.ini` (`script_location` and the store's `sqlalchemy.url`, password hidden) beside it; apply
the chain with `alembic -c <migrations>/alembic.ini upgrade head`. A title (`-m`) may hold backslashes and quotes: they are escaped in the migration's docstring.

The verb prints the written migration's path, or says the store already matches and writes nothing; both exit 0. It exits 1
for a store not at either chain's head, 2 for a flag, config or declaration it cannot read, and 3 for drift: the store holds
rows the chain never wrote (a hand SQL edit). The drift prints to stderr, a `-` line for each row the chain records and the
store lacks and a `+` line for each stored row the chain does not record; nothing is written, so the edit is never overwritten.
Revert the edit, then declare the change and revise again.

## Serving a lane's tools to the session that holds it

`GET /api/machines/board` carries a `lanes` map from the board policy (the database when its tables hold rows, else the
files): each lane's allowed harness `tools`, its typed `exits` and its bound `skill`. An exit tool exists for each event an
agent may fire from the lane: `board_review`, `board_park(reason, until)`, `board_defer(question)`, and
`board_<event>` for any other. Each carries the JSON schema generated from the lane's exits; `until` is a task id
(`TASK-9`, `TASK-9#2`; sent as `--until-task`) or a list of alert or deploy event subjects (sent as `--until`).
Every argument is text, and each is passed as `--flag=value`, so a value that starts with a dash stays a value. The tools run
the agent CLI's verbs (`task move`, `task park`): a policy exit's `trigger` is prose, so the verb
for each typed tool is fixed here, and only the tool's existence, route target and schema come from the policy.

`starpulse mcp` serves those tools to the session over stdio (MCP, one JSON-RPC message a line). It takes its task from
the `claude/task-<n>-…` branch of the working directory, or `STARPULSE_TASK`, and reads the task's lane on every
request; a lane it cannot read lists no exit tools, leaves the scope as it was and says so in `initialize`'s
`instructions`, which also carry the held lane's bound skill. It lists only that lane's exit tools and refuses any other call before anything runs. An exit that lands the
task in a lane answers with that lane's bound skill, sends `notifications/tools/list_changed`, and rewrites the
worktree's `.claude/settings.local.json` `permissions.deny` so the harness's own tools (`Agent`, `Bash`, `Edit`, …) are the
lane's `tools` and no more. A lane that declares no tools denies nothing. A denial the
operator wrote stays: the server replaces only the denials it added, which it records in `.claude/lane_scope.json` (git-ignored, like `settings.local.json`).

Nothing registers the server: it is opt-in per project (`mcpServers` in `.mcp.json`), so a project that does not name it
sees no change.

## Migrating the store

`starpulse migrate --config <c>` brings the event log to the head of its Alembic chain, builds it when empty, and runs the
one-time imports. The chain starts at one baseline revision (`0058`) that creates every table: a store at the last pre-squash
revision (`0057`) is stamped at it with no DDL and the tables nothing declares are dropped, and a store below `0057` is
refused naming the bridge release (`migrate.BRIDGE_RELEASE`), the release that carries it to `0057` first. Migrations are expand/contract for durable tables: one that only adds keeps the store readable by the release before it, and
a test fails a migration that both adds and drops. A release whose chain lacks the store's revision refuses it with `StoreNotMigrated`;
the rollback steps refuse such a target before the install. `migrate` drops the floor table an older release left.

## Backing up the store

`starpulse backup --to DIR [--keep N] [--config starpulse.toml]` writes a `VACUUM INTO` copy of the SQLite store the config
names into `DIR` as `starpulse-<local time>.db`, proves it with `PRAGMA integrity_check`, and keeps the newest `N` copies
(default 14). It prints one JSON line with the copy's path, `integrity` and the `kept` count, and exits 2 for a store that
is not SQLite, which its own backup tool owns. The read lock is held only for the copy, so `serve` keeps answering.

## Session folds in the history database

The adapters send each harness signal to the server, which folds it into the session's `ledger`, `spend`, `steps` and `cost` rows in `starpulse_signal_folds` and keeps no signal row. No verb fills or reads them: the sessions sink and a task's GraphQL `spend` field read the fold rows, and no prune deletes them.

## Reloading a running serve

`starpulse reload [--config starpulse.toml]` makes the `serve` started from that config pick up changed code and config
without a restart of the whole server. It is not an agent verb: it reads no server and `help --agent` leaves it out.
`serve` publishes a loopback endpoint and a random token in `<config stem>.control` (`starpulse.control` for
`starpulse.toml`, `starpulse-other.control` for `starpulse-other.toml`), mode `0600`, beside the config (else `starpulse.control`
in the working directory) and removes the file when it stops; `reload` reads that file, so pass the same `--config`.

`serve` reads each process's import closure from the installed code in a fresh interpreter, as a child started now would
load it: the files of the `starpulse` modules the process imports, with their content hashes. It compares that and the
process's config blocks with the last reading, taken when `serve` started or at the last `reload`, then:

- **replaced**: a child whose closure changed, or whose `database_url`, `board_type` or `board` changed, or whose Board machine file (the `[board] machine` path, read by
  content hash) changed, is ended and
  started again with a new pid. The `runs` child builds its adapters once, so a `runs`
  change also replaces it.
- **reloaded**: a child whose only change is its own config block (`pull_requests`, `repos`, `ci`, `release`,
  `task_actor` for `pulls`; `scheduler`, `level`, `session_start_url` for `scheduler`) keeps its pid and re-reads the
  config on `SIGHUP`. Where the platform has no `SIGHUP`, it is replaced instead.
- **kept**: a child with no change.
- **re-executed**: `serve` replaced itself, in place, because its own closure changed. The `api` child is replaced
  beside the old one on the shared socket, as every reload does. Each other child whose own closure and config blocks did
  not change is `kept`: the new `serve` adopts the running process by pid and its stdin pipe, so its worker, and the
  task actor's start recovery, are not interrupted. A child that changed is ended first, so it is `replaced`: the new
  `serve` starts it again.

A closure that cannot be read, such as a half-written module, or a config that does not load, changes nothing.
So does a machine definition change that drops a State holding live Tasks without a `migrations` mapping; the refusal
names the States and Tasks ([the machine registry](serving.md#machine-registry)).

It prints one JSON object, and the reply is sent before a `serve` that re-executes replaces itself:

```json
{"supervisor": "kept", "children": {"api": "replaced", "contexts": "kept"}}
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
