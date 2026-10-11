# The development loop

How I build software with many agent sessions running at once, and what StarPulse is for inside that. StarPulse is
one part of the loop. It draws the loop and enforces some of its rules; the rest is practice and ordinary tooling.
This page says what each practice is and why it is shaped that way, so you can copy the parts that suit you. It is
not a setup guide for GitHub, Dagu or any other tool StarPulse does not ship.

## What StarPulse provides and what is mine

| Practice | StarPulse provides | My own setup |
|---|---|---|
| [Trunk-based delivery on short task branches](#1-trunk-based-delivery-on-short-task-branches) | Draws each task's pull-request trail ([`[ci]`](serving.md#config-file)) | Branch naming, a worktree per task, the repository rules |
| [A human makes every merge](#2-a-human-makes-every-merge) | [The Ledger](serving.md#the-ledger) lists each merge and what applied it | The rule, an approval prompt on the merge command, and the short list of bot merges |
| [CI runs only what a change reaches](#3-ci-runs-only-what-a-change-reaches-and-the-full-suite-runs-nightly) | Nothing; its own repository's selector, `ci/select_tests.py`, is an example | The selector, the nightly full run, commit-time lint |
| [CD applies merged changes unattended](#4-cd-applies-merged-changes-unattended) | The Ledger pairs a merge with its apply run and can re-run a failed one | The apply workflow, its allowlist and its verification |
| [Scheduled workflows take fixed sequences off agents](#5-scheduled-workflows-take-fixed-sequences-off-agents) | Draws runs from Dagu, GitHub Actions or systemd; [`starpulse emit`](sources.md#report-runs-from-any-scheduler); [triggers](serving.md#triggers) | The workflows and their schedules |
| [Documentation is code and is linted](#6-documentation-is-code-and-is-linted) | Nothing | The repository, the lint, the scheduled commit |
| [Lifecycle guards refuse an out-of-order move](#7-lifecycle-guards-refuse-an-out-of-order-move) | State machines with `writers`, and [`[[board.rules]]`](public-surface.md#board-rules) | The machines and rules I declared, and the skills they name |
| [Telemetry is read back](#8-telemetry-and-projections-are-read-back-to-size-and-steer-the-next-task) | [Session health, flow health, missed skill loads, trace clusters](sources.md#measure-session-and-slice-health), [autopilot](serving.md#autopilot) | Size bands, agent profiles, what I change after reading a report |

## Scale

These numbers are a snapshot taken on 2026-10-10 (MST). Each is followed by the command that produced it; replace
`OWNER/REPO` with the repository, `MY-LOGIN` with the GitHub login that opens the pull requests and `DAGS` with the
directory of Dagu workflow files.

| Number | Command |
|---|---|
| 2,800 pull requests merged in my main repository and 263 in StarPulse, from 2026-09-10 to 2026-10-09 | `gh api -X GET search/issues -f q='repo:OWNER/REPO is:pr is:merged merged:2026-09-10..2026-10-09' --jq .total_count` |
| 838 of the last 1,000 merged pull requests in my main repository were merged by my account and 162 by a GitHub App; all 162 were bot-opened pin or digest bumps | `gh pr list -R OWNER/REPO --state merged --limit 1000 --json mergedBy,headRefName --jq '[.[] \| select(.mergedBy.login\|startswith("app/"))] \| group_by(.headRefName\|split("/")[0]) \| map({branch: (.[0].headRefName\|split("/")[0]), n: length})'` |
| A median of 11 minutes and a 90th percentile of 89 minutes from opening to merge, over the 836 of those 1,000 opened under my account | `gh pr list -R OWNER/REPO --state merged --limit 1000 --json createdAt,mergedAt,author --jq '[.[] \| select(.author.login=="MY-LOGIN") \| ((.mergedAt\|fromdate) - (.createdAt\|fromdate))] \| sort \| {n: length, median_min: (.[length/2\|floor]/60\|floor), p90_min: (.[(length*0.9)\|floor]/60\|floor)}'` |
| A peak of 23 agent sessions open at the same time over the previous 168 hours | `curl -s 'http://localhost:8766/api/analytics/sessions?hours=168' \| jq '[.sessions \| group_by(.harness+.session)[] \| {a: (map(.first_at)\|min), b: (map(.last_at)\|max)}] \| ([.[]\|[.a,1]] + [.[]\|[.b,-1]]) \| sort_by(.[0]) \| reduce .[] as $e ({c:0,p:0}; .c += $e[1] \| .p = ([.p,.c]\|max)) \| .p'` |
| 57 workflow files, 45 of them scheduled, 6 of them containing an agent step | `ls DAGS/*.yaml \| wc -l`; `rg -l '^schedule:' DAGS \| wc -l`; `rg -l 'kind: agent' DAGS \| wc -l` |

A session counts as open from its first to its last exported event, so the peak is an upper bound on sessions
actively working.

## 1. Trunk-based delivery on short task branches

**What.** One task is one branch cut from the current `main` and one pull request. The branch is rebased onto
`main`, never merged with it, and each change lands as a single commit whose subject ends in the pull request
number. Every task gets its own git worktree, so no two sessions share a working tree. The repository ruleset
requires a pull request and one passing check.

**Why.** A branch that lives for minutes is reviewed in minutes, a red build is attributable to one change, and
parallel sessions never trip over each other's files. The median above is the evidence: a change is usually merged
before there is time to forget what it was for.

## 2. A human makes every merge

**What.** Agents open a pull request, wait for CI and mark it ready. I read it and merge it. An agent never runs the
merge. The one exception is a short list of bot-opened pull requests, pin and digest bumps, that merge themselves
behind the same required check.

**Why.** CI shows that a change builds and passes; only a person decides whether it is the change that was wanted.
GitHub does not enforce this: the ruleset requires a passing check and no approving review, because agents open
pull requests under my account and GitHub never lets an author approve their own. What holds it is on my side. The
agents' instructions say never to merge, and the agent harness's permission rules put the merge command behind an
approval prompt, so a merge an agent attempts stops and asks me. The merge split above shows how much the exception
covers.

## 3. CI runs only what a change reaches, and the full suite runs nightly

**What.** A pull request, and a push to `main`, run the tests that the changed files can reach, chosen from the
import graph. A path the selector does not know runs the full suite, so a miss costs time and never coverage. The
whole suite runs on a nightly schedule. Lint runs in a git hook on a commit's staged paths, not in the pull-request
run. One required check always runs and carries its conditions on steps inside it, because GitHub treats a required
check that never reports as pending forever, not as passing.

**Why.** Running every test per change makes each change pay for every other change's tests, and with many sessions
pushing at once it saturates the runners. The cost of this choice is stated: a defect the selector cannot see is
caught by the nightly run, not before merge. StarPulse's own repository does the same; read
[`ci/select_tests.py`](../ci/select_tests.py) and [Development](development.md).

## 4. CD applies merged changes unattended

**What.** A push to `main` starts an apply. It classifies the changed paths into buckets (a container image, a
compose project, a dashboard, a system unit, a ruleset, a skill) and hands each bucket to the one script that
applies that kind of change; the router is a dispatcher, never a second implementation. A failed bucket does not
hold back an unrelated one. An apply is not done until the rebuilt thing holds: it must pass its healthcheck or stay
up through a settle window, and the revision is recorded as applied only when every bucket applied or was skipped, so
a failed event stays owed. An allowlist bounds what may rebuild unattended; a change outside it still gets its
review and then waits for a person. Only failures notify, because a held change is a steady state and a message per
tick would teach me to ignore it. The runner sits inside my network and only makes outbound connections, since
nothing outside can reach in.

**Why.** A merged change has to reach what it declares without anyone remembering to deploy it, and a hand-run
change to live state is drift that must be repaid in the same task. The allowlist exists because a reviewed merge is
not approval for an unattended rebuild of everything it touches.

## 5. Scheduled workflows take fixed sequences off agents

**What.** A stretch of work whose steps never vary becomes a Dagu workflow, and an agent calls one command instead of
several. Delivery is the example: refuse on `main`, commit, test, push, open the pull request, wait for CI, mark it
ready, ending in `green`, `red <phase>` or `blocked <phase>`. A stretch becomes a workflow only when it needs run
history, retries, visibility or a wait that should not hold an agent's turn. In an unattended run the workflow owns
the order: an agent step returns a typed result and a code step checks it before anything acts on it, an agent step
never retries itself, and a lint fails any agent step that no code step checks.

**Why.** Each step an agent takes costs tokens and gives it a chance to drift; a script does the same sequence the
same way and leaves a run history. Whoever holds a run's judgment orchestrates it, and the other side supplies
steps. This is the reason I built StarPulse to pair its lifecycle machines with the workflows I already ran:
fewer manual commands per task.

## 6. Documentation is code and is linted

**What.** Documentation lives in a version-controlled repository of its own. Each document carries frontmatter (title,
summary, tags), describes the current state rather than history, and is edited in place with no pull request. A lint
runs over the files an author edits: markdown rules, an offline link check and a content linter for structure and
frontmatter. A scheduled job commits changed documents, lints each first, and holds a failing file out of the
history; it stays on disk and fails the run until it is fixed.

**Why.** Agents read documentation and act on it, so a stale page is a wrong instruction. A lint is the one reviewer
that sees every edit, and gating the commit rather than CI means a broken document never enters the history agents
search.

## 7. Lifecycle guards refuse an out-of-order move

**What.** A task's lifecycle is a state machine declared as data: its states, its transitions and who may make each
move (the operator, an agent or a named workflow). The board writer refuses a move the machine or a
[board rule](public-surface.md#board-rules) forbids, the same way for the command line and the page, and the refusal
names the skill that satisfies it. Examples: an agent never sets `Done`, which is set only once every referenced pull
request is terminal; a test must fail before the change that makes it pass; work that changes what a page draws
cannot reach `Review` until I have seen a render. A new guard is replayed over recorded board history before it
enforces anything, so it is not corrected by its first victims.

**Why.** Agents pick a skill by recall, and recall misses. In one scored evaluation of mine, on a UI-design
workflow, no agent loaded the skill the case needed; each loaded a generic delivery skill instead. A refusal at the
write that names the next step routes them reliably. So order is enforced at the writer, and judgment, such as
whether a change is visible, stays with a skill. That evaluation is mine and not reproduced here; read it as one
observation, not a benchmark.

## 8. Telemetry and projections are read back to size and steer the next task

**What.** Sessions export their telemetry to StarPulse's receiver. From it I read, per task: model steps, operator
prompts, interrupts, compactions, whether the model or effort changed mid-task, and whether the task finished in
one session with no intervention (a clean completion). Beside it sit flow health (work in progress, stuck tasks,
throughput), the skills a session should have loaded and did not, and the recurring work that clusters across
sessions. Task sizes are bands of observed steps and minutes, and a report scores how far the newest work has drifted
from them. The model and effort for a kind and size is chosen from cost per clean completion. The autopilot admits the
next task only if its estimated demand fits the host's CPU, memory, session and review-queue limits.

**Why.** Sizing and routing guessed from memory drift; measured sessions keep them honest. Reading is still mostly
manual: a report names a gap, and I decide whether it becomes a skill, a workflow or a change to a size band.
Turning a captured signal into a changed behavior without me is not finished.
