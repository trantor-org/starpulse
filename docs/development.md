# Development

```sh
git clone https://github.com/trantor-org/starpulse && cd starpulse
uv sync
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build   # the page, built into starpulse/static; its Kanban, DAGs, Admin and Flow graph views load on demand
uv run starpulse serve
```

The build also writes `starpulse/static/one-file`, the same page as a single script, which `starpulse demo` inlines: a demo is one HTML file with no server to fetch a view's chunk from.

`uv run pytest` runs the suite with Python alone. When Docker or Podman is available, it also runs the Postgres-backed
integration cases; otherwise those cases are skipped. `uv sync --no-group hub` installs without the hub extras, as an IC
instance runs, and the suite then skips the Postgres and hub cases.
`uv sync --no-group hub --python 3.14t` is the free-threaded build, which CI runs the same selected tests on (`python-ft`, on a pull request and the nightly run, not a required check): `psycopg-binary`
has no 3.14t wheel, so hub mode stays on 3.14. `test_memray_flagged.py` skips there, since memray reports no allocation for a small test's list on that build.
`uv run pytest -n 4 --dist loadgroup` spreads it over four pytest-xdist workers (CI starts two per runner); `loadgroup` keeps the tests that
share checkout state on one worker. CI sizes `-n` to its runner's memory with `ci/xdist_workers.py`.
CI splits the suite by test file across the `python-shard` matrix (`ci/shard.py`: `SHARD_INDEX` of `SHARD_COUNT`, both unset
locally). A `select` job runs `ci/select_tests.py` once and sizes the matrix from the selection: no shard when it selects no
test, one shard per minute of the selected files' test time (never more than the files), and all six for the nightly and a
manual dispatch. `select` also runs `lint-imports` on every pull request. The `python` job, the ruleset's required check,
passes when `select` did and every shard it launched did, including when it launched none; a failed, cancelled or never-run
shard fails it.
A test that runs past 120 s (`timeout` in `[tool.pytest.ini_options]`, from pytest-timeout) fails with a timeout error;
a test that needs longer carries `@pytest.mark.timeout(<seconds>)` with the reason beside it.
The screen below runs only in the nightly full suite and a manual `workflow_dispatch`, where `ci.yml` sets `TEST_COST_REPORT=1`;
a pull request, merge-queue, push or local run prints no section, annotation or summary row and writes no report.
A test whose setup, call and teardown together pass 5 s (`SLOW_TEST_SECONDS` overrides it) is named at the end of the
run, slowest first (`ci/slow_tests.py`); in CI each is also a warning annotation on its `def` line and a row in the job
summary. A test that burns more than 5 CPU-s (`SLOW_TEST_CPU_SECONDS` overrides it; self plus waited-for children)
is named beside them with its CPU seconds and the growth of its worker's peak RSS, and the summary table has Wall s,
CPU s and Peak MB columns. Containers a test starts (Postgres, mock-oauth2) run outside the process tree, so their CPU
and memory are not counted. None of it fails the run: make the test faster, or keep it slow with a `# Stays slow:
<reason>` comment directly above its `def`, naming what the test must pay for (a server process, a container, a cold
import).
With `TEST_COST_REPORT=1` the flagged tests' node id, wall s, CPU s and peak MB also go to `test-cost.json`
(`TEST_COST_REPORT_PATH` moves it), and each shard reruns exactly those tests one by one under `pytest --memray`
(`ci/memray_flagged.py`), then uploads the report and `memray/` (one allocation report per test plus `stats.json`) as the
`test-cost-<shard>` artifact; a test whose rerun left no report is named in `stats.json` and a `::warning`.
`starpulse/tests/conftest.py` keeps the suite's fixed costs low: every SQLite connection runs `PRAGMA synchronous=OFF`, and one
background thread starts the session's Postgres and mock-issuer containers when collection finishes, so a test waits on
a warm container instead of paying its start.
CI runs only the tests a pull request or a merge-queue candidate can reach (`ci/select_tests.py`); a push to main
runs none, because the merge queue tested that very commit, and the full suite runs nightly and on a manual dispatch. CI's `static-checks` job imports every module an IC instance can load without the hub extras
(`ci/ic_imports.py`) rather than running the suite a second time. This repository is public, so its `ci/public_names.py` check fails
when a tracked file other than a workflow, the runner-label list or a test names the operator's private hosts; docs, comments and fixtures use neutral names.
A pull request's CI runs only the test files its changes can reach, chosen by `ci/select_tests.py` from the import
graph; a dependency, `conftest.py`, fixture, machine, schema or skill change runs the whole suite.
`uv run lint-imports` checks the tiers under `starpulse/_internal`, top to bottom: `api` over `cli` (the server's routes and
the hub, then the command line), `adapters`, `level`, `feed` and `ci`, `eventlog`, then `config`, `machines` and
`contracts`. A package imports its own tier or one below; none import upward, and `feed` and `ci` never import each other.
The top level holds only the public modules the [Public surface](public-surface.md#public-surface) lists, each a facade over its feature.
`pnpm --dir starpulse/web run check` typechecks, lints, tests and builds the page.
The page's `web/src` is organized by feature: `api/` (types, `apiFetch`, the event stream), `features/<name>/` (a view with its
pure model and colocated tests), `render/` (the canvas), `shared/` and `demo/`. oxlint's `no-restricted-imports` (`.oxlintrc.json`) holds a feature
to `api/`, `render/`, `shared/` and its own folder, so a feature never reaches into another's.
Every `/api` body is a pydantic model in `starpulse/contracts/api.py`, and the server builds each response through it.
The page's types are generated from those models: after changing one, run `uv run python -m starpulse.contracts.api`
(writes `starpulse/api.schema.json`) and `pnpm --dir starpulse/web run gen:types` (writes `starpulse/web/src/api/types.gen.ts`),
and commit both. CI's `static-checks` job regenerates them and fails on any difference.
[`bench/`](../bench/README.md) holds the hub-ingest, instance event-log and flow-read benchmarks, the page-latency harness that times every
request and page surface against the 50 ms budget, and a Locust load test that holds that budget under many viewers.

[`design/`](../design/index.html) is the design mockup, a static page over a saved snapshot (`data.js`) and, behind
`?view=kanban`, a saved Board (`board.js`) drawn by `kanban.js`; both hold synthetic tasks only, never a real board's titles; view it with
`uv run python -m http.server 8781 --directory design`, and `uv run python -m starpulse._internal.cli.demo --mockup design --out
mockup.html` writes it as one scrubbed file. A pull request that changes the page (`starpulse/web/**`), the mockup or
the preview itself gets one UI-preview comment from
[`.github/workflows/ui-preview.yml`](../.github/workflows/ui-preview.yml): screenshots of each changed surface's
scrubbed demo, built by [`ci/ui_preview.py`](../ci/ui_preview.py) against the demo config
[`ci/preview.toml`](../ci/preview.toml), with the demos published to the `gh-pages` branch of `trantor-org/starpulse`, which GitHub Pages serves, under `pr-<N>/`
while the pull request is open. That config draws a fictional workspace at a working team's scale: the Board adapter
[`ci/demo_workspace.py`](../ci/demo_workspace.py) serves an eight-lane Board whose In Progress opens a delivery machine and
the lifecycle machines in [`ci/workspace/`](../ci/workspace), beside five DAG domains, and `starpulse._internal.cli.demo` fills it with
synthetic tasks, sessions, runs and pools. Each changed sub-mockup, a `design/<dir>/index.html` layered over a scrubbed page
capture, is published beside the demos as `mockup-<dir>.html` with its scripts inlined. The preview is review context and never gates the pull request. A change confined to one view's
feature folder (`features/kanban`, `features/dags` or `features/orbit`) screenshots that view alone; any other page path screenshots all four.
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
