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
`uv run pytest -n 4 --dist loadgroup` spreads it over four pytest-xdist workers; `loadgroup` keeps the tests that
share checkout state on one worker. CI sizes `-n` to its runner's memory with `ci/xdist_workers.py`.
CI runs only the tests a pull request or a push to main can reach (`ci/select_tests.py`); the full suite runs
nightly and on a manual dispatch. CI's `ic` job imports every module an IC instance can load without the hub extras
(`ci/ic_imports.py`) rather than running the suite a second time.
A pull request's CI runs only the test files its changes can reach, chosen by `ci/select_tests.py` from the import
graph; a dependency, `conftest.py`, fixture, machine, schema or skill change runs the whole suite, and so does every
push to `main`.
`uv run lint-imports` checks the tiers under `starpulse/_internal`, top to bottom: `api` over `cli` (the server's routes and
the hub, then the command line), `adapters`, `level`, `feed` and `ci`, `eventlog`, then `config`, `machines` and
`contracts`. A package imports its own tier or one below; none import upward, and `feed` and `ci` never import each other.
The top level holds only the public modules the [Public surface](public-surface.md#public-surface) lists, each a facade over its feature.
`pnpm --dir starpulse/web run check` typechecks, lints, tests and builds the page.
The page's `web/src` is organized by feature: `api/` (types, `apiFetch`, the event stream), `features/<name>/` (a view with its
pure model and colocated tests), `render/` (the canvas), `shared/` and `demo/`. ESLint's `no-restricted-imports` holds a feature
to `api/`, `render/`, `shared/` and its own folder, so a feature never reaches into another's.
Every `/api` body is a pydantic model in `starpulse/contracts/api.py`, and the server builds each response through it.
The page's types are generated from those models: after changing one, run `uv run python -m starpulse.contracts.api`
(writes `starpulse/api.schema.json`) and `pnpm --dir starpulse/web run gen:types` (writes `starpulse/web/src/api/types.gen.ts`),
and commit both. CI's `api-types` job regenerates them and fails on any difference.
[`bench/`](../bench/README.md) holds the hub-ingest, instance event-log and flow-read benchmarks, the page-latency harness that times every
request and page surface against the 50 ms budget, and a Locust load test that holds that budget under many viewers.

[`design/`](../design/index.html) is the design mockup, a static page over a saved snapshot (`data.js`) and, behind
`?view=kanban`, a saved Board (`board.js`) drawn by `kanban.js`; view it with
`uv run python -m http.server 8781 --directory design`, and `uv run python -m starpulse._internal.cli.demo --mockup design --out
mockup.html` writes it as one scrubbed file. A pull request that changes the page (`starpulse/web/**`), the mockup or
the preview itself gets one UI-preview comment from
[`.github/workflows/ui-preview.yml`](../.github/workflows/ui-preview.yml): screenshots of each changed surface's
scrubbed demo, built by [`ci/ui_preview.py`](../ci/ui_preview.py) against the demo config
[`ci/preview.toml`](../ci/preview.toml), with the demos published to `trantor-org/starpulse-demo` under `pr-<N>/`
while the pull request is open. That config draws a fictional workspace at a working team's scale: the Board adapter
[`ci/demo_workspace.py`](../ci/demo_workspace.py) serves an eight-lane Board whose In Progress opens a delivery machine and
the lifecycle machines in [`ci/workspace/`](../ci/workspace), beside five DAG domains, and `starpulse._internal.cli.demo` fills it with
synthetic tasks, sessions, runs and pools. Each changed sub-mockup, a `design/<dir>/index.html` layered over a scrubbed page
capture, is published beside the demos as `mockup-<dir>.html` with its scripts inlined. The preview is review context and never gates the pull request. A push to `main`
that touches the same paths republishes both demos under `main/`, the [live demo](https://trantor-org.github.io/starpulse-demo/main/flow-view.html), with a screenshot of each flow-view view that the README shows.

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
