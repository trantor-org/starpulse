---
name: mitigate
description: Stops a failing or runaway service, process or container from getting worse before diagnosing it, rechecks its health, and asks why only once it is green. Use when a process pins CPU or memory, a disk is filling, a service is down or crash-looping, a container is unhealthy, or an alert reports live impact, before reading its logs or profiling it. Not for a failure that has already stopped, a failing test, or a postmortem.
machine: machine.yaml
---

# Mitigating a Failing Service

This phase ends when the failing target is healthy and its cause is filed, or when a person holds the next lever.
Live impact comes first: while it grows, every minute spent asking why costs more than the evidence it buys, and a
host starved of CPU, memory or disk slows the investigation too.

A step named `starpulse command run NAME` is the project's own command. When it exits 4 the project maps no
`NAME`: do that step as the project's `AGENTS.md` says.

## 1. Assess the impact

Run `starpulse command run health -- <target>` once: a process id, a service unit or a container. It samples the
target and reports it failing or healthy. Read only what decides the lever: which target, how far past normal, and
whether that number is still climbing. Do not open its logs, a profiler or its source yet.

Done when one command names the failing target and whether its impact is growing.

## 2. Keep what the lever destroys

A lever that kills or restarts erases the process's memory, open files and stack.
Capture only what the lever would destroy, in one bounded command.
Run `starpulse command run snapshot -- <target>`; logs, metrics and history outlive the lever, so leave them for
step 5. When the impact threatens the host or the session itself, skip this step.

Done when the snapshot names the file it wrote, or you have said why you skipped it.

## 3. Pull a lever

Apply the least destructive lever that stops the growth. In order: stop sending it work, terminate it, kill it,
restart it, roll back its last change. Run it with `starpulse command run mitigate -- <target> <lever>`.

The project's `AGENTS.md` says which targets you may act on without asking, such as processes your own session
started and the repairs it catalogues.
A lever the project does not authorize, or one that destroys state, goes to a person.
Park the task with `starpulse task park <task> --operator '<target>: <lever> to stop <impact>'`, and ask for
the lever first and the investigation second.

Done when the lever ran, or a person holds the ask.

## 4. Recheck health

Rerun the health command from step 1 against the same target. Still failing: take the next lever on the list.

Done when the health check that failed now passes.

## 5. Diagnose

Only now ask why. Read the snapshot, the logs and the history the lever left intact, and record the cause and its
evidence with `starpulse task edit <task> --append-notes`.

Done when the notes name the cause and the command that showed it.

## 6. File the follow-up

The lever bought time; it did not remove the cause. File the durable fix as a task, or fix it under starting-task.

Done when the task notes link the follow-up task or its pull request.

## Decline the investigation reflex

- Never read logs, profile or search the code for a target whose impact is still growing; pull a lever first.
- Never wait for a root cause before a lever. A wrong guess at the cause costs the time the lever would have saved.
- A request to diagnose a live failure is answered with the lever first and the diagnosis after it.
