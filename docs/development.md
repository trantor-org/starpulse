# Development

```sh
git clone https://github.com/trantor-org/starpulse && cd starpulse
uv sync
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build   # the page, built into starpulse/static; its Kanban, DAGs and Admin views load on demand
uv run starpulse serve
```

The build also writes `starpulse/static/one-file`, the same page as a single script, which `starpulse demo` inlines: a demo is one HTML file with no server to fetch a view's chunk from.

`uv run pytest` runs the suite with Python alone: every store a test opens is a SQLite file.
`tests/e2e/` holds the tests that run an operator's entry point end to end;
`addopts` deselects them, so no default, pull-request or nightly run pays their seconds, and
`uv run pytest -m e2e` runs them. Each piece such a test composes keeps a fast integration test of its own.
`uv sync --python 3.14t` is the free-threaded build, which CI runs the same selected tests on (`python-ft`, on a pull request and the nightly run, not a required check). `test_memray_flagged.py` skips there, since memray reports no allocation for a small test's list on that build.
`uv run pytest -n 4 --dist worksteal` spreads it over four pytest-xdist workers (CI starts two per runner); `worksteal`
lets an idle worker take tests queued behind a busy one, so one slow file spreads across workers. Tests are safe to run
on any worker: tests that stub the checkout's `static` directory share it through
`tests/page_stub.py`. CI sizes `-n` to its runner's memory with `ci/xdist_workers.py`.
CI splits the suite by test file across the `python-shard` matrix (`ci/shard.py`: `SHARD_INDEX` of `SHARD_COUNT`, both unset
locally). A `select` job runs `ci/select_tests.py` once and sizes the matrix from the selection: no shard when it selects no
test, one shard per minute of the selected files' test time (never more than the files), and all six for the nightly and a
manual dispatch. `select` also runs `lint-imports` on every pull request. The `python` job, the ruleset's required check,
passes when `select` did and every shard it launched did, including when it launched none; a failed, cancelled or never-run
shard fails it.
A test that runs past 120 s (`timeout` in `[tool.pytest.ini_options]`, from pytest-timeout) fails with a timeout error;
a test that needs longer carries `@pytest.mark.timeout(<seconds>)` with the reason beside it.
A test's ceiling is 5 s for setup, call and teardown together (`SLOW_TEST_SECONDS` overrides it). In every run but the
nightly, the pull-request gate and a local run included, a test fails at teardown past three times that
(`SLOW_TEST_FAIL_SECONDS` overrides it; `ci/slow_tests.py`), stretched by the host's 1-minute load per CPU when that is above 1 (`SLOW_TEST_LOAD_SCALE=0` turns it off): the gate's host is shared, and one 0.7 s test took 9.4 s at a
load of 4.6 per CPU. A test that already failed or errored is not failed again. Make a slow test faster, or keep it slow with `@pytest.mark.slow` and a `# Stays slow: <reason>`
comment directly above it naming what the test must pay for (a server process, a container, a cold import).
`OVER_CEILING` there lists the tests at or over 4 s when the bound landed, each with the slice that brings it under; that
slice removes its entry. A budget test (leak, latency, soak) carries
`@pytest.mark.nightly`: `addopts` deselects it, and only the nightly suite and a manual dispatch run it (`-m "not e2e"`
in `ci.yml`'s `python-shard`).
The screen below runs only in the nightly full suite and a manual `workflow_dispatch`, where `ci.yml` sets `TEST_COST_REPORT=1`
(and on `python-ft`, which reports and never fails the ceiling); any other run prints no section, annotation or summary row
and writes no report. A test over 5 s is named at the end of the run, slowest first; in CI each is also a warning annotation
on its `def` line and a row in the job summary. A test that burns more than 5 CPU-s (`SLOW_TEST_CPU_SECONDS` overrides it; self plus waited-for children)
is named beside them with its CPU seconds and the growth of its worker's peak RSS, and the summary table has Wall s,
CPU s and Peak MB columns. Containers a test starts run outside the process tree, so their CPU
and memory are not counted. None of the screen fails the run.
With `TEST_COST_REPORT=1` the flagged tests' node id, wall s, CPU s and peak MB also go to `test-cost.json`
(`TEST_COST_REPORT_PATH` moves it), and each shard reruns exactly those tests one by one under `pytest --memray`
(`ci/memray_flagged.py`), then uploads the report and `memray/` (one allocation report per test plus `stats.json`) as the
`test-cost-<shard>` artifact; a test whose rerun left no report is named in `stats.json` and a `::warning`.
The same nightly and dispatch runs record which source files each test executes: every shard runs
`--cov --cov-context=test` (line coverage of `starpulse` and `ci`, `[tool.coverage.run]`) and uploads its data as
`coverage-data-<shard>`. The `coverage-map` job, after all shards pass and no required check, combines them
and `ci/coverage_map.py build` writes `<sha>.json` and `latest.json` (`{sha, collected, tests: {node id: [files]}}`) to
`$STARPULSE_COVERAGE_MAP_DIR`, default `~/.cache/starpulse-ci/coverage-map` of the CI runner user, which the
`ci-sp-python` select step also runs as. A parametrized case with no context of its own takes its function's files; a
collected test with no files is left out. `uv run python ci/coverage_map.py latest` prints the newest map's sha and how
many collected tests it names; it exits 1 before the first nightly published one.
Each background context has a leak gate, `tests/unit/leaks/test_context_budgets.py`: it drives the context's loop
for a fixed number of iterations against a fixture board and a throwaway SQLite store, and fails when the memory still held
afterwards exceeds the context's budget (`pull-events: retained 41000 B over 200 iterations, budget 32768 B exceeded`).
It is marked `nightly`, so the nightly suite runs it and no pull request does. Run it locally with
`uv run pytest -m nightly tests/unit/leaks`. The harness is
[`tests/leak_gate.py`](../tests/leak_gate.py): it warms the loop up, then measures two consecutive windows
under `memray.Tracker` and takes the smaller one's leaked allocations after `gc.collect()`, so a one-time allocation (one 1 MiB
SQLite allocation per process) lands in one window and never fails the gate, while a leak shows in both. To change a
budget, edit the context's `Budget(iterations, retained_bytes)` in `BUDGETS` there: measure the new baseline with the gate
(the failure message prints the retained bytes) and set the budget about twice the baseline, never to the leak's size.
Baselines on CPython 3.14.6 and memray 1.20.0: pull-events 12 880 B over 200 iterations, scheduler 11 680 B over 100 (the
scheduler tick rereads its growing ledger, so its cost grows with the square of the iterations); budgets 32 KiB each. The gate skips on 3.14t, where memray reports no allocation, and under `pytest --memray`, which cannot nest a
tracker. A context joins by adding a driver to `test_context_budgets.py` and an entry to `BUDGETS`.
`tests/conftest.py` keeps the suite's fixed costs low: every SQLite connection runs `PRAGMA synchronous=OFF`.
The required checks run only the tests a pull request or a merge-queue candidate can reach (`ci/select_tests.py`), as the
`ci-sp-*` checks of the sp-ci Dagu DAG (`ci/run.sh` is its entry point; `ci/reach.py` skips a job the change cannot reach); `ci.yml`
has no pull-request or merge-group trigger, a push to main runs none, because the merge queue tested
that very commit, and the full suite runs nightly and on a manual dispatch from `ci.yml`. A nightly fresh-serve run (the `fresh-serve` job in `ci.yml`, on a dedicated worker so it competes with no other CI) builds main's wheel, installs it into an empty virtualenv, starts `starpulse serve` from an empty directory with no config and a bare environment, and runs `ci/fresh_serve.py`, which fails unless `/` answers HTTP 200 and every worker the supervisor names (read from the pid `serve` logs for its context, since a zygote-forked child shows the zygote's argv in `ps`) is alive below `serve` on two checks five seconds apart with the same processes. It proves the out-of-the-box install is the production install. The canary (`ci/canary_smoke.py`, image `ci/canary/Dockerfile`) proves a candidate against a copy of live state: it migrates a `VACUUM INTO` copy of the store to the wheel's head, serves with the live config and machines (relative reads resolve against the live config directory; writes such as `state_dir` go to scratch, so the run switch is never read; board commands are dropped), checks `starpulse reload` exits 0, holds 60 seconds with no worker restart, then opens the board and a task modal in Chromium. The image runs free-threaded CPython 3.14t, as live does, and runs with `--network none` and no secrets (each token variable the config names gets a placeholder). A store migrated past the wheel's head fails at `migrate:` before anything serves. The image builds from the checkout root after `pnpm --filter @starpulse/web build`, with `--build-context vendor=<dir holding the patched aioquic and pylsqpack>`, since neither publishes a 3.14t wheel; the header of `ci/canary/Dockerfile` has the build and run commands. The `macos-fresh-serve` job in `ci.yml` runs the same script on a GitHub-hosted macOS runner in the nightly run and on a manual dispatch (the fleet is Linux), so the supervisor, the resident-size reader and the Page API's handed socket are proven there too; prove a pull request by dispatching `ci.yml` on its branch. This repository is public, so its `ci/public_names.py` check fails
when a tracked file other than a workflow, the runner-label list or a test names the operator's private hosts; docs, comments and fixtures use neutral names.
A pull request's CI runs only the test files its changes can reach, chosen by `ci/select_tests.py` from the per-test
coverage map the nightly full suite records (`ci/coverage_map.py`): a changed file selects the tests that executed it. A
file the map lacks, such as a new module, falls back to the import graph, and a changed test file selects itself. A
machine, skill or `pyproject.toml` lint-table edit selects the tests of the code that reads it; only a dependency,
`conftest.py` or fixture change, or any other `pyproject.toml` edit, runs the whole suite.
`uv run lint-imports` checks the tiers in `pyproject.toml`, top to bottom: the entrypoints (`runtime`, `views`, `cli`),
the producers (`pulls`, `scheduler`, `sessions`, `runs`, `harness_telemetry`), the derived `flow_metrics` and `board`, then
the core (`event_log`, `machine_engine`, `github`, `contracts`). A package imports its own tier or one below,
and siblings on one line never import each other. `runtime` and `cli` are the only composition roots: no context
imports them, and `runtime` owns the root config loader (`starpulse/runtime/config.py`) that reads `starpulse.toml` and
hands each context its typed section, which lives in that context (`[scheduler]` in `scheduler/model/config.py`, for
one); `cli` reads the same loader. The `store-table-private` contract lets only the event store import its tables, so
every stream write goes through `EventStore`. The `context-*` contracts hold each bounded context to the contexts
upstream of it; `event_log`, `analytics`, `github`, `signals` and `contracts` are the shared kernel and belong to none.
The top level holds only the public modules the [Public surface](public-surface.md#public-surface) lists, each a facade over its feature.
`pnpm --dir starpulse/web run check` typechecks, lints, tests and builds the page.
The page's `web/src` is organized by feature: `api/` (types, `apiFetch`, the event stream), `features/<name>/` (a view with its
pure model and colocated tests), `render/` (the canvas), `shared/` and `demo/`. oxlint's `no-restricted-imports` (`.oxlintrc.json`) holds a feature
to `api/`, `render/`, `shared/` and its own folder, so a feature never reaches into another's.
Every `/api` body is a pydantic model under `starpulse/contracts/api/dto/`, and the server builds each response through it (`starpulse/views/encoding.py`).
The page's types are generated from those models: after changing one, run `uv run python -m starpulse.contracts.api`
(writes `starpulse/schemas/api.schema.json`) and `pnpm --dir starpulse/web run gen:types` (writes `starpulse/web/src/api/types.gen.ts`),
and commit both. CI's `static-checks` job regenerates them and fails on any difference.
[`bench/`](../bench/README.md) holds the instance event-log and flow-read benchmarks, the page-latency harness that times every
request and page surface against the 50 ms budget, and a Locust load test that holds that budget under many viewers.

[`design/`](../design/index.html) is the design mockup, a static page over a saved snapshot (`data.js`) and, behind
`?view=kanban`, a saved Board (`board.js`) drawn by `kanban.js`; both hold synthetic tasks only, never a real board's titles; view it with
`uv run python -m http.server 8781 --directory design`, and `uv run python -m starpulse.cli.demo --mockup design --out
mockup.html` writes it as one scrubbed file. A pull request that changes the page (`starpulse/web/**`), the mockup or
the preview itself gets one UI-preview comment from
[`.github/workflows/ui-preview.yml`](../.github/workflows/ui-preview.yml): screenshots of each changed surface's
scrubbed demo, built by [`ci/ui_preview.py`](../ci/ui_preview.py) against the demo config
[`ci/preview.toml`](../ci/preview.toml), with the demos published to the `gh-pages` branch of `trantor-org/starpulse`, which GitHub Pages serves, under `pr-<N>/`
while the pull request is open. That config draws a fictional workspace at a working team's scale: the Board adapter
[`ci/demo_workspace.py`](../ci/demo_workspace.py) serves an eight-lane Board whose In Progress opens an in-progress machine of Build, Deliver and Review-fix phase machines, with
the other lifecycle machines in [`ci/workspace/`](../ci/workspace), beside five DAG domains, and `starpulse.cli.demo` fills it with
synthetic tasks, sessions, runs and pools. Each changed sub-mockup, a `design/<dir>/index.html` layered over a scrubbed page
capture, is published beside the demos as `mockup-<dir>.html` with its scripts inlined. The preview is review context and never gates the pull request, so a failed render leaves the run green.
A final workflow step then replaces the comment with one titled "failed" that names the head commit, links the run and carries no screenshots,
and the next push renders again. A change confined to one view's
feature folder (`features/kanban` or `features/dags`) screenshots that view alone; any other page path screenshots all three.
A push that changed none of those paths since the commit the comment names leaves the comment and the demos untouched, and of `ci/` only
the preview script, its config, the demo adapter and `ci/workspace/` start a run. A push to `main`
that touches the same paths republishes both demos under `main/`, the [live demo](https://trantor-org.github.io/starpulse/main/starpulse.html), with a screenshot of each starpulse view that the README shows.

## Flow read scaling

Flow health and the level read the summaries the history store keeps on write, so a read costs the activity of its
window, of the trailing 12 weeks (the level's aging threshold) and of the tasks still in flight, not the length of the
history. [`bench/flow_reads.py`](../bench/flow_reads.py) records 10 thousand, 1 million and 10 million Board lane changes at
a fixed rate into a SQLite store and reads the default week of each: the CPU p95 of health, the level and its trajectories
at 1 million and at 10 million stayed within 1.6x of the p95 at 10 thousand in every run (one run: health 6.5, 6.3 and
8.0 ms; level 171, 142 and 180 ms; trajectories 164, 135 and 155 ms), and no read touches the two raw tables. The full table and how to
rerun it are in [`bench/README.md`](../bench/README.md#flow-reads). What still grows with the history: opening a store
whose summaries are empty folds every row once (about 6 minutes for 10 million lane changes), and a history that
supplies only `lane_rows` and `level_runs`, or a level on a machine other than the Board, is read whole.
