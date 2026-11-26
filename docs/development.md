# Development

```sh
git clone https://github.com/trantor-org/starpulse && cd starpulse
uv sync
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build   # the page, built into starpulse/static; its Kanban, DAGs and Admin views load on demand
uv run starpulse serve
```

`uv run pytest` runs the suite with Python alone: every store a test opens is a SQLite file.
`tests/e2e/` holds the tests that run an operator's entry point end to end;
`addopts` deselects them, so no default, pull-request or nightly run pays their seconds, and
`uv run pytest -m e2e` runs them. Each piece such a test composes keeps a fast integration test of its own.
`uv sync --python 3.15t` is the free-threaded build, which CI runs the same selected tests on (`python-ft`, on a pull request and the nightly run, not a required check). `test_memray_flagged.py` skips there, since memray reports no allocation for a small test's list on that build.
`uv run pytest -n 4 --dist worksteal` spreads it over four pytest-xdist workers (CI starts two per runner); `worksteal`
lets an idle worker take tests queued behind a busy one, so one slow file spreads across workers. Tests are safe to run
on any worker: tests that stub the checkout's `static` directory share it through
`tests/page_stub.py`. CI sizes `-n` to its runner's memory with `ci/xdist_workers.py`.
CI runs the suite as one pytest session: `ci/run.sh python-tests` syncs one locked venv and starts work-stealing xdist
workers (`-n <workers> --dist worksteal`). On the build host the count fits the `tests.slice` memory budget
(`ci/xdist_workers.py --slice`); on any other runner it follows the runner's memory limit. A `select` job runs
`ci/select_tests.py` once and prints `python=false` when it selects no test, which skips the run, and `python=true` with
the targets otherwise (the nightly and a manual dispatch select the whole suite). The `static-checks` job runs
`lint-imports` and `ruff check` (the pyflakes rules, so an unused import or an undefined name fails) beside the other short checks. The `python` job, the ruleset's required check, passes when `select` did and
the one run did, including when `select` chose no test.
A test that runs past 120 s (`timeout` in `[tool.pytest.ini_options]`, from pytest-timeout) fails with a timeout error;
a test that needs longer carries `@pytest.mark.timeout(<seconds>)` with the reason beside it.
A budget test (leak, latency, soak) carries `@pytest.mark.nightly`: `addopts` deselects it, and only the nightly suite and a
manual dispatch run it (`-m "not e2e"` in the `python` job of the `starpulse-nightly` pipeline). No plugin screens a test's
time: `pytest --durations=20` lists the slowest locally, `pytest --memray` profiles one test's allocations, and
`pytest-timeout` fails a test that is still running after 120 s.
The nightly's `python` job (and a manual dispatch) writes the run's JUnit report, `junit.xml` in the run directory, where
each test's `time` is its setup, call and teardown together. `ci/memray_flagged.py JUNIT OUT_DIR` then reruns every test
over 5 s, slowest first, one by one under `pytest --memray` and leaves in OUT_DIR (`memray/` in the nightly) one allocation report per test
plus `stats.json`; a test whose rerun left no report is named in `stats.json` and a `::warning`. A test that grows
slow fails nothing: it shows only in that list.
The same nightly and dispatch runs record which source files each test executes: the run adds
`--cov --cov-context=test` (line coverage of `starpulse` and `ci`, `[tool.coverage.run]`) and uploads its data as
`coverage-data`. The `coverage-map` job, once the select job passed and whether the run was green or red (a
red nightly still uploads its data, and a map frozen behind it goes stale), combines it
and `ci/coverage_map.py build` writes `<sha>.json` and `latest.json` (`{sha, collected, tests: {node id: [files]}, functions: {file: {function: [positions in tests]}}}`) to
`$STARPULSE_COVERAGE_MAP_DIR`, default `~/.cache/starpulse-ci/coverage-map` of the CI runner user, which the
`ci-sp-python` select step also runs as. A parametrized case with no context of its own takes its function's files; a
collected test with no files is left out. `uv run python ci/coverage_map.py latest` prints the newest map's sha and how
many collected tests it names; it exits 1 before the first nightly published one. `build` publishes nothing and exits 1
when the map names under 90% of the collected tests (a run that crashed outright uploaded no data). The select step
prints `COVERAGE_MAP_SHA`, `COVERAGE_MAP_AGE_HOURS`, `COVERAGE_MAP_FILES` and `COVERAGE_MAP_MISSING` (the named source
files the checkout no longer has, which a moved module causes); sp-ci records them in the run's `ci-run-facts` as
`coverage_map`.
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
scheduler tick rereads its growing ledger, so its cost grows with the square of the iterations); budgets 32 KiB each. The gate skips on 3.15t, where memray reports no allocation, and under `pytest --memray`, which cannot nest a
tracker. A context joins by adding a driver to `test_context_budgets.py` and an entry to `BUDGETS`.
`tests/conftest.py` keeps the suite's fixed costs low: every SQLite connection runs `PRAGMA synchronous=OFF`.
The required checks run only the tests a pull request or a merge-queue candidate can reach (`ci/select_tests.py`), as the
`ci-sp-*` checks of the sp-ci pipeline (`ci/run.sh` is its entry point; `ci/reach.py` skips a job the change cannot reach). The public repository runs no GitHub Actions workflow: the merge queue tests every commit, and the full suite runs nightly as the `starpulse-nightly` pipeline (`sp-nightly`; rerun it for a manual run). A nightly fresh-serve run (the `fresh-serve` job of that pipeline, on a worker so it competes with no other CI) builds main's wheel, installs it into an empty virtualenv, starts `starpulse serve` from an empty directory with no config and a bare environment, and runs `ci/fresh_serve.py`, which fails unless `/` answers HTTP 200 and every worker the supervisor names (read from the pid `serve` logs for its context) is alive below `serve` on two checks five seconds apart with the same processes. It proves the out-of-the-box install is the production install. The canary (`ci/canary_smoke.py`, image `ci/canary/Dockerfile`) proves a candidate against a copy of live state: it migrates a `VACUUM INTO` copy of the store to the wheel's head, serves with the live config and machines (relative reads resolve against the live config directory; writes such as `state_dir` go to scratch, so the run switch is never read; board commands are dropped), checks `starpulse reload` exits 0, holds 60 seconds with no worker restart, then opens the board and a task modal in Chromium. The image runs GIL CPython 3.14 with the locked stock wheels, as live does, and runs with `--network none` and no secrets (each token variable the config names gets a placeholder). A store migrated past the wheel's head fails at `migrate:` before anything serves. The image builds from the checkout root after `pnpm --filter @starpulse/web build`; the header of `ci/canary/Dockerfile` has the build and run commands. This repository is public, so its `ci/public_names.py` check fails
when a tracked file other than a workflow, the runner-label list or a test names the operator's private hosts; docs, comments and fixtures use neutral names.
A pull request's CI runs only the test files its changes can reach, chosen by `ci/select_tests.py` from the per-test
coverage map the nightly full suite records (`ci/coverage_map.py`): a changed file selects the tests that executed it. When
the edit only changes function or method bodies (read from the pull request's base text, compared as syntax trees), it
selects only the tests that ran those functions, as node ids, a file when half or more of its tests ran one; a
constant, signature, decorator, class attribute, added or removed def, a function the map never saw, a map without
`functions` or a path with no base text selects every test that ran the file. A test whose session-scoped fixture or
import-time call alone ran a function can be missed; the nightly full run is what catches it. A
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
pure model and colocated tests), `render/` (the canvas), and `shared/`. oxlint's `no-restricted-imports` (`.oxlintrc.json`) holds a feature
to `api/`, `render/`, `shared/` and its own folder, so a feature never reaches into another's.
Every `/api` body is a pydantic model under `starpulse/contracts/api/dto/`, and the server builds each response through it (`starpulse/views/model/encoding.py`).
The page's types are generated from those models: after changing one, run `uv run python -m starpulse.contracts.api`
(writes `starpulse/schemas/api.schema.json` and `starpulse/schemas/openapi.json`) and `pnpm --dir starpulse/web run gen:types`
(writes `starpulse/web/src/api/types.gen.ts`), and commit all three. CI's `static-checks` job regenerates them, fails on any
difference, and runs `redocly lint` on the OpenAPI document (rules in `starpulse/web/redocly.yaml`).
A route is declared once in `ROUTES` in `starpulse/contracts/api/registry.py`, with its summary, query names and DTOs; the OpenAPI
document is built from that table, and `tests/unit/contracts/test_openapi.py` fails when the document, the registry and the
routes the app mounts disagree. Each route takes one tag from the first segment of its path (`TAGS` and `_tag` in
`starpulse/contracts/api/openapi.py`); a route whose segment has no tag fails the build, so add the segment there.
[`bench/`](benchmarks.md) holds the instance event-log benchmark, the page-latency harness that times every
request and page surface against the 50 ms budget, and a Locust load test that holds that budget under many viewers.

[`design/`](../design/index.html) is the design mockup, a static page over a saved snapshot (`data.js`) and, behind
`?view=kanban`, a saved Board (`board.js`) drawn by `kanban.js`; both hold synthetic tasks only, never a real board's titles; view it with
`uv run python -m http.server 8781 --directory design`. [`ci/ui_preview.py`](../ci/ui_preview.py) builds the public demos: the page
is the normal multi-file build replaying a recording of a seeded server's reads, read-only
([`ci/demo_recording.py`](../ci/demo_recording.py) crawls the server and [`ci/replay.js`](../ci/replay.js) answers the page's `/api`
reads from it, refusing a write), and the design mockup and element sheet are each one scrubbed file
([`ci/design_demo.py`](../ci/design_demo.py)). The seeded server runs against the demo config [`ci/preview.toml`](../ci/preview.toml). That config draws a fictional workspace at a working team's scale: the native board over the machines in
[`ci/.starpulse/machines/`](../ci/.starpulse/machines) is an eight-lane Board whose In Progress opens an in-progress machine of Build, Deliver and Review-fix phase machines, with
the other lifecycle machines beside it, and five DAG domains, and [`ci/seeded_server.py`](../ci/seeded_server.py), the one seeder the screenshots and the latency gate share, fills it with
synthetic tasks.

After a push to `main` that changes the page (`starpulse/web/**`) or another preview input, the
`starpulse-ui-preview` Woodpecker workflow runs `ci/ui_preview.py --main`, which republishes both demos under `main/` on the
`gh-pages` branch GitHub Pages serves: the [live demo](https://trantor-org.github.io/starpulse/main/starpulse.html),
with a screenshot of each starpulse view that the README shows. Pull requests get no published preview.
