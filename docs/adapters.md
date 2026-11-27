# The native board

StarPulse serves its own Markdown board directly: the server, the page and the task actor call the native board's
functions, with no board adapter contract between them, and a `[board]` table can no longer name an outside module. Its
`type` is `native`, the only board and the default. The runs and machine-events
contracts are unchanged (see the adapter-writing skill). Pluggable boards, a Jira or Linear board for example, are
withdrawn until a second tracker is planned (see ADR Pluggable boards are withdrawn).

The `starpulse.board.Board` the server holds says:

- which lifecycle machines the page draws (`machines`),
- how its tasks reach the page (`start`, which feeds each task as it changes, and `keys`, the task keys it
  recognizes),
- a `writer(task, status, actor)` for moves made on the page or by an agent (each task's `moves` may list the
  `writers` the machine declares per event), an `assign` for assignee changes, a `read`, `edit` and `archive` for the
  full task record and guarded edits and archives, a `restore(task)` that returns an archived or retired task to
  the board (`PUT /api/tasks/{id}` with `archived: false`), a `retire(task)` and `retired(task)`
  that keep a finished task in the history store instead (`PUT /api/tasks/{id}` with `retired: true`,
  `GET /api/retired[?task=<id>][&fields=dependencies]`), a `complete(task)` that takes a
  Done task out of the lanes (archived, where `read` and `edit` still find it), and a `create(title, details)`
  that makes a task whole, in one write, in the board's starting lane or the lane a `status` detail names, with the
  details the page filled (description, priority, impact, urgency, labels, milestone, assignee, dependencies,
  acceptance criteria, type, references, documentation, Definition of Done) and answers with its id
  (`PUT /api/tasks`),
- milestone records: `milestones()`, `read_milestone(id)`, `create_milestone(title, details)` (answering with the new
  id), `edit_milestone(id, changes)` and `archive_milestone(id)` (`POST /api/milestones` lists, `GET /api/milestones/<id>` reads, `PUT /api/milestones` creates,
  `PUT /api/milestones/<id>` upserts over the `revision` a read named as `base`, and `DELETE /api/milestones/<id>`
  archives; the writes answer only the loopback and private network),
- and doc records the same way: `docs()` (without bodies), `read_doc(id)`, `create_doc(title, details)`,
  `edit_doc(id, changes)`, `archive_doc(id)` and `restore_doc(id, folder)` (`POST /api/docs` lists the `ids` it names,
  `GET /api/docs/<id>`, `PUT /api/docs`, `PUT /api/docs/<id>` and `DELETE /api/docs/<id>`; `archived: false` in the
  upsert restores).

`serve` records every machine event (task- and run-keyed) and each Board lane change it
  places into StarPulse's own store (`starpulse_machine_events`, `starpulse_lane_changes`), and the page reads that
  store: a `Board` has no history of its own.

`starpulse.board.adapters.native`, the default, holds a task only in its History (the `task` event stream) and writes no
task file: a move, assignee change, new task, edit or archive appends to that stream, and a task is read back for the task
view (priority, description, acceptance criteria, plan, notes and definition of done) from it alone, on the board page, the
API and `starpulse task show --markdown`. Nothing writes under the board's `tasks/`, `completed/` or `archive/tasks/`;
`starpulse import-board` and `starpulse parity` alone read a legacy file there, and `parity --import --remove`, once no
task is missing a History, removes the files the deploy leaves. An archive appends `Archived` after a reason is added to
the task's comments; a restore returns the task to the board's tasks and never replaces a task there.
A move, edit or reopen out of Done returns a completed task to its lane, and a restore does the same for a
task whose status already left Done, which the board would otherwise hold as archived.
A retire takes a finished task off the
board into the history store's `starpulse_retired_tasks` table (migration 0017), one row per front matter `id` with
the file's name and text byte for byte and its front matter `milestone` (indexed with the id, migration 0065), so a read
by id or milestone probes an index; event-log pruning never touches it; a board keeps none until it starts,
since the table is in the store it starts on. A new task numbers past every retired one, a transition rule's dependency
condition reads the status its text holds, a scan settles one whose text is Done as completed (so `workable`, `is_done` and `waiting_on` count a dependency on it done, and an archived one whose text is not Done stays unplaced), and a restore returns it to the board and drops the row, never replacing a task there.
A board that starts on a store gives each retired row with no History a `TaskImported` of its record and an `Archived`, once, so the retired task is in History before the table goes; retiring an archived task appends no second `Archived`.
An import keeps a file a client held the same way, accepting the same text again and refusing other text under a
kept number or a task still on the board.
Every task write is one append to the task's History: an edit applies all its changes and every comment it carries (one text
or a list, in order) at once, and a create also sets any further field an edit sets (`status`, `type`, `references`,
`documentation`, `definitionOfDone`, `plan`, `notes`) in the same write, refusing the whole create on a field it cannot
set. Each write stamps `updated_date`, and a create `created_date`, in UTC as `YYYY-MM-DD HH:MM`.
The `[board] task_file_name` setting is retired: a config that still sets it loads, and the setting does nothing.
A task's front matter `aliases` list holds the keys it was known by before. A lookup by an alias finds the task, a new id never
reuses one, and the feed holds one card for the task.
With `[board] validate` set to `module:function`, the board imports that function when it loads (a name that resolves
to no function is a startup error) and calls it before every task write with the file's path, its text before the write
(`None` for a create) and the text about to be written. A returned string refuses the write: the writer answers with it
as its refusal and writes nothing, so a refused create leaves no file and its id to the next create. `None` lets the
write land.
With `[board] python_path` set to a list of directories relative to the config file, the board puts each at the front
of `sys.path` before it imports `validate`, so a hook that lives in the deployment's own source imports without the
operator exporting `PYTHONPATH`; a directory that does not exist is a startup error naming the key.
With `[[board.guards]]` set, the board judges each task write against those rules first, as the actor that makes it, and
a rule broken refuses the write with its `reason` and `skill` before `validate` is asked (see Board guards in
[public-surface.md](public-surface.md)); the `edit`, `archive`, `create` and `assign` writers take that actor as a
keyword, `edit(task, changes, comment, actor="agent")`, which the server always passes on `edit`, `archive` and `create`
(`anonymous` when the request names none); a `create` writer's `details` also carry `created_by`, the writer's
`<harness>:<session>` to stamp in the task.
A task record also carries `start_criteria`: each entry of the `start_criteria` YAML block under the description's
`## Start Criteria` heading (`id`, `kind`, `expr`), as written and never evaluated; a Done task's is empty. A Waiting
task waits on events: each `kind: event` entry names an event subject (`query`), and the task actor releases the task on
the first event of any of them (see Serving). The `[board] criteria` key is still read and does nothing.
Each open task in the snapshot carries `workable` and `workable_since` (epoch seconds, null when not workable). A task is
not workable while a dependency is not done (completed, or in the `done` lane) or while it is Waiting on an event its
Start Criteria name; a Waiting task with neither is workable. It is workable since the latest of when it entered its lane
and when each dependency was done.
The native board also keeps milestones in Backlog.md's format, so a Backlog.md project's milestone files read
unchanged: `milestones/m-N - slug.md`, with the front matter `id` and `title` and, under `## Description`, the sections `## Outcome`, `## Spec`
and `## ADRs` (bullet lists) and `## Retro`. The slug is the title lowercased, whitespace to `-`, `<>:"/\|?*` removed
and cut to 50 characters. A new milestone takes the next number past every file in `milestones/` and
`archive/milestones/`; an edit rewrites only the sections it names (keeping unknown sections and the text before the
first heading byte for byte) and renames the file when the title changes, and an archive moves the file to
`archive/milestones/`.
It keeps docs in Backlog.md's format too: `docs/<folder>/doc-N - slug.md`, with the front matter `id`, `title`, `type`
(`specification`, `guide`, `readme`, `postmortem` or `other`), `created_date` and `updated_date` and the doc's text after it. A
subfolder of `docs/` such as `specs/` is part of the doc's path and stays through every edit. The slug is the title
with `<>:"/\|?*` read as a space, `'(),` dropped and runs of space made `-`, its case kept. A new doc takes the next
number past every file in `docs/` and `archive/docs/`; an update rewrites only the front matter lines it changes (and
`updated_date`) and the body it is given, renames the file when the title changes, and writes nothing when it
changes nothing; an archive moves the file to `archive/docs/`, and a restore moves it back unchanged into the folder it
names under `docs/` (`docs/` itself by default), never replacing a file there.
The native board's task `edit` appends every field of Backlog.md's task record and only the one it is given: the front
matter's `title`, `type`, `status` (spelled as the board's lane), `priority`, `impact`, `urgency` (each `low`, `medium` or `high`, or empty), `milestone`, assignee (`profile`),
`labels`, `dependencies`, `references`, `documentation` and `modifiedFiles` (an empty one of the last three leaves its
key out), and the body's description, plan, notes, final summary, acceptance criteria and definition of done (an item
with its `n` keeps it, one without takes the next after the highest `n` given, so a list given without numbers is
numbered from 1). `appendNotes` adds a line to the end of the notes, a non-blank
`comment` adds a comment, and `read` returns the comments as `{created, text}`, which an edit cannot set. `complete(task)`
refuses a task that is not Done and archives one that is.
`starpulse.board.adapters.native_scan` is the one-shot scan of the legacy task files that `import-board` and `parity` read (no directory watch runs; the `interval` setting is retired), puts every task in the team named by its `config.yml`'s
`project_name` (a project that sets none is refused, so no task lands in a default team), takes
the machine from the project's own statuses (any lane reaches any other, unless `machine` names a machine file
whose states are those lanes and whose `writers` reserve a move to an actor, such as `operator`); the native board's
writer lands the moves. Its first scan is the feed's replay, as a
stream adapter's read up to its start is: the feed builds the Ledger once, after the scan has placed every file, and a
task write that meets the scan waits for it, so even a full scan serves the whole board in seconds. The native board
also keeps itself saved: the feed saves its Board with each scanned file's fingerprint (modification time and size)
and task, and a restart resumes that Board and re-reads only the files added, changed or removed since, so unchanged
files are never read again. The save is keyed by the project alone and records a hash of the projection code, the
project's `config.yml` and the machine file; a deploy that changes any of them keeps the saved Board, reads every file
again and publishes only the tasks that project differently. A save that cannot be read starts from a full scan.
