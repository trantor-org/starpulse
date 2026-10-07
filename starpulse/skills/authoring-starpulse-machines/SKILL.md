---
name: authoring-starpulse-machines
description: Writes and checks the lifecycle machine YAML that StarPulse draws and enforces, with `starpulse machine validate` and `starpulse machine import mermaid`. Use when asked to add or change a board's columns, states, events, transitions, guards, writers (who may make a move, such as operator-only) or subflows, or to turn a Mermaid stateDiagram into a machine file.
---

# Authoring StarPulse Machines

A machine is a YAML file, by convention under `.starpulse/machines/`; `[board] machine` in `starpulse.toml` names the
Board's. The file is the source of truth: a `.mmd` diagram is generated from it, never the reverse. The file holds
data only: no expressions or code, so never write a condition as a script.

## Write the machine

1. Start from the shape, naming every state and event:

   ```yaml
   name: board
   states:
     ready: {initial: true}
     in_progress: {}
     review: {}
     done: {final: true}
   events:
     START: [{from: ready, to: in_progress}]
     RETURN_READY: [{from: in_progress, to: ready}]
     SUBMIT: [{from: in_progress, to: review, if: {when: {pr: {exists: true}}}}]
   bindings: {claim: START}
   writers:
     RETURN_READY: [{actor: operator, trigger: the board page}]
   ```

2. `states` need exactly one `initial: true`; ids are lower-case `[a-z][a-z0-9_]*`. A `final` state ends the flow.
3. Each `events` entry is a list of transitions: `from` is one state or a list, `to` is one state, and both must be
   declared. A transition may carry `if` or `unless`, and an `action`.
4. A guard is `{when: {field: {equals: v}}}`, `{in: [..]}` or `{exists: true|false}` against the triggering event's
   fields (every listed field must match), or the name of a guard the adapter registers in Python. A `when` field may
   not be `event`, `event_data`, `machine`, `model`, `source`, `state`, `target` or `transition`.
5. `bindings` maps an adapter's own event name to the machine event it moves.
6. `writers` names, per event, who fires it: `actor` is a bare name (`agent`, `operator`) or `<instance>/<workflow>` for
   a workflow a configured runs adapter lists, and `trigger` is how it fires. A move to an actor outside the event's
   writers is refused with the reason; an event with no `writers` entry may be made by any actor. Every `writers` key
   must be an event the machine declares.
7. A subflow is a state with `flow: child.yaml`, a path relative to this file. The child's states nest under it as
   `<state>_<child state>`. Only one level is allowed, a `flow` state cannot be `final`, and a child may not bind an
   adapter event the parent binds.
8. `source` names a third party that moves the machine, such as `GitHub`. StarPulse only observes a machine with a
   `source`, and the page draws it apart from one its own actors move. Leave it out for a machine StarPulse moves.

Done when the file names its states, events, bindings and writers and every event a writer fires is declared.

## Validate it

1. Run `starpulse machine validate .starpulse/machines/board.yaml`, passing the parent and each child file. It reads
   no server and answers `{ok, machines: [{path, ok, errors}]}`, each error `{file, line, message}`.
2. Exit 1 means a file was refused: fix the error at its line and run it again.
3. A guard or action given by name is not checked here, because the adapter registers it; a name the adapter does not
   register is refused when the adapter loads the machine.

Done when `ok` is true for every file.

## Import a Mermaid diagram

1. Run `starpulse machine import mermaid flow.mmd --out .starpulse/machines/flow.yaml`. It drafts the file from a
   `stateDiagram-v2` and answers `{written}`; it never overwrites an existing file, so pick a new `--out`.
2. Edit the draft: events are named from the transition labels (`Deps done` becomes `DEPS_DONE`), and guards, actions,
   bindings and writers are left for you to add.
3. Run `starpulse machine validate` on the result.

Done when the drafted file validates and carries the guards and writers the diagram could not.
