## Why This Matters
On 2026-10-27 the operator asked for StarPulse's contexts to show what each module is for, and chose hexagonal + CQRS.
doc-1020 D1–D3 place every `pulls` module in a role subpackage under one `layers` contract.

## Current State
`starpulse/starpulse/pulls/` holds 12 modules flat beside `__init__.py`; 54 StarPulse src and test
files import a moving module path. Docs naming module paths: `/home/adinb/trantor-docs/services/ai/starpulse/adapters.md`.

## Scope
Move each module with `git mv` per this placement (doc-1020 Today, checked clean by a layer-check script):
- `pulls/model/`: `ci`, `pins`
- `pulls/application/commands/`: `ci_trail`
- `pulls/adapters/inbound/`: `pull_refresh`, `delivery`, `task_actor`, `unblock`
- `pulls/adapters/outbound/`: `github`, `pull_store`, `pulls`, `pull_requests`, `pull_events`

Create the empty `__init__.py` files `starpulse/starpulse/pulls/adapters/__init__.py`, `starpulse/starpulse/pulls/adapters/inbound/__init__.py`, `starpulse/starpulse/pulls/adapters/outbound/__init__.py`, `starpulse/starpulse/pulls/application/__init__.py`, `starpulse/starpulse/pulls/application/commands/__init__.py`, `starpulse/starpulse/pulls/model/__init__.py`. Rewrite every import of the old paths
in `starpulse/starpulse`, `starpulse/tests` and `starpulse/pyproject.toml` contract lines. Add the `pulls-layers`
contract. Rewrite the docs' module paths (edit Trantor docs at their `/home/adinb/trantor-docs/` path). Leave `pulls/pulls.py` as a re-exporting module (`from starpulse.pulls.<new path> import *` plus its `__all__`) for Trantor's direct import (D5 expand); T10 deletes it.


## Constraints
Pure move: no behavior change, no rename or split of a module. The package `__init__` exports exactly today's names.
The test tree keeps its layout. `task_actor` and `unblock` sit in adapters/inbound because they import `pull_requests.PULL_URL`, and `pull_requests`/`pull_events` sit in adapters/outbound because they annotate `pulls.PullStore` (D2). A module whose placement breaks `lint-imports` moves to the
nearest outer layer that passes, and the PR body lists each such move (D2). This slice is a wide rename: nothing else
in StarPulse's `pulls` or the import-linter block runs beside it.

## Stop Conditions
A placement that passes no layer, a cycle `lint-imports` reports that a move cannot break, or a Trantor import of a
moved path not named in doc-1020 Today: stop and comment on the task.

## ADR Needed
No: the Bounded Contexts ADR amendment (T1) covers it.

## Implementation Plan
1. On `origin/main`, capture `uv run --directory starpulse python -c "import types, starpulse.pulls as m; print('\n'.join(sorted(n for n in dir(m) if not n.startswith('_') and not isinstance(getattr(m, n), types.ModuleType))))" > .tmp/pulls-names-before.txt`.
2. `git mv` each module per Scope; add the subpackage `__init__.py` files.
3. Rewrite imports with `rg -l` + `sed` over src, tests, pyproject and the docs; run `uv run ruff check --fix` for
   import order.
4. Add the contract after `board-layers`, in the same shape:
   `[[tool.importlinter.contracts]] id = "pulls-layers" type = "layers" containers = []
   layers = ["starpulse.pulls.adapters", "starpulse.pulls.application.commands", "starpulse.pulls.model"]`.
5. Run the criteria.

Mechanism: `git mv` + import rewrite; contract shape from `starpulse/pyproject.toml:183` (`board-layers`) and the `|`
sibling syntax at `starpulse/pyproject.toml:69`.

## Duplicate Search

role subpackages; layers contract; hexagonal; flow_metrics model adapters; re-export history scores

Terminal candidates: TASK-2422 (completed), TASK-2504 (completed), TASK-2619 (completed), TASK-3505 (completed), TASK-4315 (completed), TASK-4724 (completed), TASK-4729 (completed), TASK-6201 (completed), TASK-6733 (Done), TASK-7731 (Archived)

Open candidates: TASK-7729 (Review), TASK-7738 (In Progress), TASK-9248 (In Progress)

## Duplicate Resolution

TASK-7729 and TASK-7730 (m-314 Board and Scheduler layers) are Done; TASK-5156 and TASK-7731 are completed or archived predecessors; TASK-7738 (Pulls and Runs became packages) is Done and only packaged them flat. None found open. Cohort siblings filed from doc-1020: TASK-9248, TASK-9250.
