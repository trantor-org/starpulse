# Write a board adapter

A board adapter connects StarPulse to a tracker. It is a module with a `board(settings, base)` function that
returns a `starpulse.board.Board`: `settings` is the rest of the `[board]` table and `base` is the config file's
directory. The `Board` says:

- which lifecycle machines the page draws (`machines`),
- how the tracker's tasks reach the page (`start`, which feeds each task as it changes, and `keys`, the task
  keys it recognizes),
- and optionally a `writer(task, status, actor)` for moves made on the page or by an agent (each task's `moves` may
  list the `writers` the machine declares per event), an `assign` for assignee changes, a `read`, `edit` and `archive` for the full task record and guarded edits and
  archives (`edit` needs `read`; the snapshot's `capabilities` says which the board has), a `complete(task)` that
  moves a Done task out of the lanes (the native board's to `completed/`, where `read` and `edit` still find it), a `create(title, details)` that
  makes a task in the board's starting lane with the details the page filled (description, priority, labels,
  milestone, assignee, dependencies, acceptance criteria) and answers with its id (`POST /api/tasks`;
  `capabilities.create`), and optionally milestone records: `milestones()`, `read_milestone(id)`,
  `create_milestone(title, details)` (answering with the new id), `edit_milestone(id, changes)` and
  `archive_milestone(id)` (`GET /api/milestones`, `GET /api/milestones/<id>`, `POST /api/milestones`,
  `POST /api/milestones/edit` and `POST /api/milestones/archive`; the writes answer only the loopback and private
  network, and a board that sets none answers 404), and doc records the same way: `docs()` (without bodies),
  `read_doc(id)`, `create_doc(title, details)`, `edit_doc(id, changes)` and `archive_doc(id)` (`/api/docs`,
  `/api/docs/<id>`, `/api/docs/edit` and `/api/docs/archive`). `serve` records every machine event (task- and run-keyed) and each Board lane change it
  places into StarPulse's own store (`starpulse_machine_events`, `starpulse_lane_changes`), and the page reads that
  store: a `Board` has no history of its own. In the same transaction the store folds each of them into
  summaries a read of flow health or the level can use instead of every row: `starpulse_step_summaries` (steps and
  seconds in the from-state, per UTC day, machine, from-state and to-state), `starpulse_cases` (each task's or run's
  current state, when it entered it and its last event), `starpulse_lane_intervals` (each stay in a lane) and
  `starpulse_lanes` (per source and lane, the tasks in it now and when one first entered it). A store whose summaries
  are empty builds them from its rows when it opens (`HistoryStore.build_summaries`), and one that predates the lane
  counts counts them from its intervals; `rebuild_summaries` replaces them and `summary_differences` lists where they
  differ from the rows. A hub gets the tables from its migrations (revisions `0005` and `0007`). The summaries follow
  the order events were recorded, and cover only the machines the page draws when the store opens.
  `/api/analytics/health` and `/api/level` (with `/api/level/trajectories`) read these summaries and never scan the two
  raw tables: health reads the stays that ended in its window or are still going and takes the tasks in each lane from
  the lane counts; the Board's level reads the trajectories of the tasks that changed lane in its window or the trailing
  12 weeks (which set the aging threshold) and of the tasks still waiting or working, and takes where the history begins
  and which sources reported from the lane counts. Their cost follows that activity, not the history's length (see
  [Flow read scaling](development.md#flow-read-scaling)). A history that supplies only `lane_rows` and `level_runs`, as the Board adapter
  hook does, is read whole, and a level on a machine other than the Board reads that machine's events whole.

`starpulse._internal.board.native`, the default, keeps tasks as Markdown files under `.starpulse/board/` and writes moves,
assignee changes and new tasks to them in Python, reads a task's full record (priority, description, acceptance
criteria, plan, notes and definition of done) back for the task view, applies an edit to a task's file in one write,
and archives a task by moving its file to `archive/tasks/` after a reason is appended to its comments.
Every task write is one rename of a whole file: an edit applies all its changes and every comment it carries (one text
or a list, in order) at once, and a create also sets any further field an edit sets (`status`, `type`, `references`,
`documentation`, `definitionOfDone`, `plan`, `notes`) in the same write, refusing the whole create on a field it cannot
set. Each write stamps `updated_date`, and a create `created_date`, in UTC as `YYYY-MM-DD HH:MM`.
With `[board] task_file_name` set to `slug`, a create writes `task-<n>-<slug>.md` in place of the default `title` form,
`task-<n> - <Title>.md`: the slug is the title in lowercase letters and digits joined by hyphens, cut at a word to at
most 19 characters with a trailing `YYYY-MM-DD` kept past the cut, and `untitled` for a title with neither. A value
other than `title` or `slug` is a startup error. The setting names only files a create writes; an existing file keeps
its name, and every later write to a task reuses its file.
With `[board] validate` set to `module:function`, the board imports that function when it loads (a name that resolves
to no function is a startup error) and calls it before every task write with the file's path, its text before the write
(`None` for a create) and the text about to be written. A returned string refuses the write: the writer answers with it
as its refusal and writes nothing, so a refused create leaves no file and its id to the next create. `None` lets the
write land.
With `[[board.rules]]` set, the board judges each task write against those rules first, as the actor that makes it, and
a rule broken refuses the write with its `reason` and `skill` before `validate` is asked (see Board rules in
[public-surface.md](public-surface.md)); the `edit`, `archive`, `create` and `assign` writers take that actor as a
keyword, `edit(task, changes, comment, actor="agent")`, and the server passes it only when the request names one.
A task record also carries `start_criteria`: each criterion of the `start_criteria` YAML block under the
description's `## Start Criteria` heading (`id`, `kind`, `expr`, `cmp` and `want` for its threshold), with its
`status` (`met`, `unmet`, `error` or `not evaluated`), `observed` value, `error` and `checked` time. With `[board]
criteria` set to a command, the server runs it in the config's directory with `{id}` replaced by the task's id, and
reads a JSON array from its output, one object per criterion with `id`, `status` (`met`, `not-met` or `error`),
`observed`, `error` and `checked_at`; its exit status is ignored when it prints that array. A task's results are reused for 30
seconds. A command that fails to start, runs longer than 10 seconds, prints no array, or leaves a criterion out marks the
affected criteria `error` with why, and the record still builds. With no command each criterion is `not evaluated`.
Each open task in the snapshot carries `workable` and `workable_since` (epoch seconds, null when not workable). A task is
not workable while a dependency is not done (completed, or in the `done` lane) or while it is Waiting and its Start
Criteria are not all met; `not evaluated` and `error` count as unmet, and a Waiting task with neither criteria nor
dependencies is workable. It is workable since the latest of when it entered its lane, when each dependency was done and
when a pass first saw its criteria all met. The server evaluates the criteria of Waiting tasks whose dependencies are
done in the background every 30 seconds through the same cache, never per page, and keeps that first-met moment in
`starpulse_criteria_met` while the criteria stay met, so a restart does not reset it.
The native board also keeps milestones in Backlog.md's format, so a Backlog.md project's milestone files read
unchanged: `milestones/m-N - slug.md`, with the front matter `id` and `title` and, under `## Description`, the sections `## Outcome`, `## Spec`
and `## ADRs` (bullet lists) and `## Retro`. The slug is the title lowercased, whitespace to `-`, `<>:"/\|?*` removed
and cut to 50 characters. A new milestone takes the next number past every file in `milestones/` and
`archive/milestones/`; an edit rewrites only the sections it names (keeping unknown sections and the text before the
first heading byte for byte) and renames the file when the title changes, and an archive moves the file to
`archive/milestones/`.
It keeps docs in Backlog.md's format too: `docs/<folder>/doc-N - slug.md`, with the front matter `id`, `title`, `type`
(`specification`, `guide`, `readme` or `other`), `created_date` and `updated_date` and the doc's text after it. A
subfolder of `docs/` such as `specs/` is part of the doc's path and stays through every edit. The slug is the title
with `<>:"/\|?*` read as a space, `'(),` dropped and runs of space made `-`, its case kept. A new doc takes the next
number past every file in `docs/` and `archive/docs/`; an update rewrites only the front matter lines it changes (and
`updated_date`) and the body it is given, renames the file when the title changes, and writes nothing when it
changes nothing; an archive moves the file to `archive/docs/`.
The native board's task `edit` writes every field of Backlog.md's task file and only the one it is given: the front
matter's `title`, `type`, `status` (spelled as the board's lane), `priority`, `milestone`, assignee (`profile`),
`labels`, `dependencies`, `references`, `documentation` and `modifiedFiles` (an empty one of the last three leaves its
key out), and the body's description, plan, notes, final summary, acceptance criteria and definition of done (an item
with its `n` keeps it, one without takes the next). `appendNotes` adds a line to the end of the notes, a non-blank
`comment` adds a comment, and `read` returns the comments as `{created, text}`, which an edit cannot set. `complete(task)`
refuses a task that is not Done and moves one that is to `completed/`.
`starpulse._internal.board.upstream_backlog` is the reference adapter for a tracker with its own
writer: it polls a Backlog.md project's Markdown files, puts every task in the team named by its `config.yml`'s
`project_name` (a project that sets none is refused, so no task lands in a default team), takes
the machine from the project's own statuses (any lane reaches any other, unless `machine` names a machine file
whose states are those lanes and whose `writers` reserve a move to an actor, such as `operator`), and writes moves
with the `backlog` CLI, answering a failed write with the CLI's output. An adapter with a writer subclasses
`BoardAdapterKit` with `writer` set, and the kit then checks that a move the operator may make is written and one
the machine leaves to the operator is refused to the agent. A board kit also declares `teams`, the team key the
adapter derives for each task it produces, and asserts each record carries it. `starpulse._internal.board.jira` reads a Jira project and has no writer. It imports the named workflow from the site's
`workflows/search` as the Board machine (a state per status, an event per transition, a global transition leaving every
other status), refusing a workflow with a status in no transition, two statuses that make one lane, or no single initial
transition. Each issue is a task in the lane of its status and the team of its Jira project; an issue it `Blocks` waits on
the blocker, and a status in Jira's done category settles it as `completed`. Name your module in `[board] type` and StarPulse imports it.

**Migrating from `Board.history`.** `Board.history` is removed: StarPulse's store is the only history, so a `Board`
that passes `history=` fails with `TypeError: Board.__init__() got an unexpected keyword argument 'history'`. Delete
the argument, and have the adapter report what happens to a task through `start` (the feed records each lane change it
places) or the event log; the page, `/api/history`, `/api/analytics/health` and `/api/level` read the store. To keep an
existing history, copy its lane changes and machine events into the store's `starpulse_lane_changes` and
`starpulse_machine_events` tables once; `HistoryStore.rebuild_summaries` then rebuilds the summaries over them.
