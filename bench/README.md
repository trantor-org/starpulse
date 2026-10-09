# Benchmarks

Three scripts measure the event log at the two ends of a deployment and the reads of the store beside it, a fourth
times a running page against its latency budget, and a fifth holds that page open idle to see it degrade. They are not
part of the installed package and the test suite does not run them; `ci/test_page_latency.py` and `ci/test_soak.py`
hold the two page harnesses' rules.

| Script | Measures | Needs |
| --- | --- | --- |
| `hub_ingest.py` | N forwarder processes writing event batches into one Postgres event log; the insert is idempotent on `event_id`, as a hub's ingest is | a throwaway Postgres 17 |
| `ic_event_log.py` | concurrent fail-open appends to an instance's SQLite WAL log while a reader polls by cursor, at 10 thousand and 1 million rows | a scratch file path |
| `flow_reads.py` | the p95 of flow health, the level and its trajectories over a SQLite store of 10 thousand, 1 million and 10 million lane changes, read from the summaries the store keeps on write | a scratch directory with room for about 6 GB |
| `page_latency.py` | the p50 and p95 of every read route, the event stream's first snapshot, and in Chrome the first paint (navigation to the frame that draws the board), each view switch, a task modal, the Star Map's fly-to, each stream event to paint and the page's frames, against 50 ms (16.7 ms a frame) | a running StarPulse and Google Chrome |
| `soak.py` | one idle tab held open for hours: every 10 minutes the budget probed and the task modal opened and closed, every few minutes the JS heap, DOM nodes, listeners, idle frames per second, and the server's RSS, threads and open files | a running StarPulse and Google Chrome |

Run them from the repository root after `uv sync`; `page_latency.py` and `soak.py` also need `uv sync --group bench`.

## Hub ingest

```sh
docker run --rm -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=bench postgres:17
uv run python bench/hub_ingest.py                 # the DSN above
uv run python bench/hub_ingest.py <sqlalchemy-dsn>
```

The script drops and recreates `starpulse_events` in the database it connects to, so point it only at a
throwaway server. It prints one line per run: events per second and the p50, p99 and max batch latency, then
the row count, bytes per row and the cost of a tail poll.

## Instance event log

```sh
uv run python bench/ic_event_log.py .tmp/bench-events.db
```

The script replaces the file it is given, along with its `-wal` and `-shm` files. Each append opens a fresh
connection, as a short-lived `starpulse emit` does. It prints one line per table size: appends per second, the
append and cursor-poll p50 and p99, and the database size.

## Flow reads

```sh
uv run python bench/flow_reads.py .tmp/bench-flow                  # 10 thousand, 1 million and 10 million
uv run python bench/flow_reads.py .tmp/bench-flow 10000 1000000 --scan 1000000
uv run python bench/flow_reads.py .tmp/bench-flow --reuse          # read the stores a run left
```

The script records synthetic Board lane changes at a fixed rate (about 125 a day) into a SQLite store, summarises
them as the store does at start-up, and asks `/api/analytics/health`, `/api/level` and `/api/level/trajectories`
for the default week 60 times each. It prints the p95 in wall and CPU time with the statements each read sends, and
exits 1 when the CPU p95 at any size is over 2x the first size's. `--scan N` also times the whole-table reads the
summaries replaced, on the stores up to N events.

Result (ai-vm-1, SQLite, 60 reads each; the host was shared at a load average of 200, so one stalled read sets the wall p95, e.g. the 2101 ms
at 10 thousand, and the CPU time judges):

| Events | Health p95 (wall / CPU) | Level p95 (wall / CPU) | Trajectories p95 (wall / CPU) | Store |
| ---: | --- | --- | --- | ---: |
| 10 thousand | 8.6 / 6.5 ms | 2101 / 171 ms | 226 / 164 ms | 3 MB |
| 1 million | 6.3 / 6.3 ms (x0.98) | 157 / 142 ms (x0.83) | 152 / 135 ms (x0.82) | 280 MB |
| 10 million | 15.0 / 8.0 ms (x1.24) | 280 / 180 ms (x1.05) | 173 / 155 ms (x0.95) | 2.9 GB |

The ratios are the CPU p95 against the 10 thousand row, all under 2x. Run to run on this shared host they moved
by up to 1.5x on the 6 to 15 ms health read and by 1.2x on the level, in both directions, with no trend in the size. Each read sends 5 or 7 statements at every size,
health fetches under 100 rows (72 at 10 thousand, 98 at 1 million: a row per lane and per task in flight, not per lane
interval) and none touches `starpulse_machine_events` or `starpulse_lane_changes`. Before the summaries the same reads folded
every lane change: at 1 million, health took 9.2 s and the level 11.6 s (p95 of 3 reads, wall). At 10 thousand the
level reads the whole history, because the trailing 12 weeks that set the aging threshold reach back past its start;
that is the most it ever reads, and why the level's cost stays where it is as the history grows. Loading 10 million
lane changes took about a minute and `rebuild_summaries` about 6 minutes.

Rates depend on the host, so compare runs on the same machine.

## Page latency

```sh
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766 --no-page --json .tmp/latency.json
```

`--assets DIR` draws the page from a local build while its `/api` requests still go to the URL, so a branch's page
change is timed against a live server's data before it ships:

```sh
pnpm --dir starpulse/web exec vite build --outDir "$PWD/.tmp/page-build" --emptyOutDir
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766 --assets .tmp/page-build
```

`--viewer` times the page as a viewer's own machine would draw it while the server keeps its host's load. The bench,
Chrome included, re-runs in a user systemd scope (`systemd-run --user --scope -p CPUWeight=10000`), because a viewer's
browser does not share the server's CPU. Without it, a loaded host starves the measuring browser as well, and even a
view switch that draws nothing new reads over budget:

```sh
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766 --assets .tmp/page-build --viewer
```

That weight outweighs only the scope's siblings in the user manager's `app.slice`; work in `system.slice` still
competes with the browser. So the run reads its scope's `cpu.pressure` before and after, and when the scope waited for
CPU over `STARVED_SHARE` (5%) of the run, it ends the table with a `STARVED` line, sets `starved` in the JSON and exits
2, neither a pass nor a failure: its rows measure the host's load, not the page.

A task modal's sample hovers its card for 150 ms before the click, as a hand slows onto a target, and ends at the
second frame after a dialog outside any `[inert]` ancestor clears `aria-busy`, which it does once it holds the full
record. A modal the page drew ahead of the click waits inert, and the row's note counts the opens that found one.

It only reads: it opens task modals and closes them, and switches views, but never writes. It drives the system
Chrome (`--channel chrome`), so Playwright's own browser download is not needed. It prints one row per surface with
its sample count, p50, p95 and budget, marks a row over budget `OVER`, and lists every `/api` request the page made
that no row times. It exits 1 on either, so a new page request is measured before it can pass. A route that needs a
record (`/api/task/<id>`) reads the first one the server's snapshot or listing holds; a route the server does not
serve reports its status in the row's note. Wall-clock times on a busy host carry its load: run it more than once
before reading one slow row as a regression.

`--repeat N` times every surface N times and judges each row on the median run's p95 (the lower median for an even
count), so one starved run on a loaded runner neither fails a row nor hides a slow one; the row's note lists every
run's p95. `--what-if FROM TO` names the lanes for `/api/level/what-if` (default `Ready` `In Progress`), which a
server's level must have seen a task leave.
`--ceiling "ROW=MS"` holds a row with a known overrun to MS instead of 50: the row still fails past it and its note
says it is over the budget until its fix lands. The gate holds the first paint of the board at 120 ms (79 ms p95 on a
quiet slot) until the page work in TASK-3334 to TASK-3337 cuts it; drop the flag then.

## Latency gate

trantor's nightly whole-repo gate runs it (`make starpulse-latency`, `bin/starpulse_latency_gate.sh` in trantor) against
the starpulse commit trantor pins; pull requests do not, because on the shared `validate` lane it was the slowest job and
red from host load alone. It builds the page, serves `ci/seeded_server.py` (`ci/preview.toml`'s workspace with the real
request handler, a month of lane history for about 160 tasks and a level), runs `page_latency.py --repeat 3` against it
and fails on a row over budget or an untimed request. `ci/seeded_server.py` runs the same server by hand:

```sh
uv run python -m ci.seeded_server --port 8766 --dir .tmp/gate
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766 --repeat 3 --what-if in_progress review
```

The seeded board is smaller than a live one: a cost that grows with the board is the nightly `soak.py`'s to find.

## Soak

```sh
uv run --group bench python bench/soak.py http://127.0.0.1:8766 --duration 24h --report .tmp/soak.json
uv run --group bench python bench/soak.py http://127.0.0.1:8766 --duration 60m --sample-every 3m --report .tmp/soak.json
```

It opens the page in one Chrome tab and leaves it untouched, reusing `page_latency.py`'s probe. Every `--sample-every`
(5 minutes) it records the tab's JS heap after a garbage collection, DOM nodes, event listeners, animation frames per
second and the renderer's busy share over 5 idle seconds, and the server process's RSS, threads and open files. The
process is the one listening on the URL's port on this host, found again at every sample so a restart shows as a new
pid (`--pid` pins one; a server on another host reports the tab only). Every `--interval` (10 minutes) it times each read route and the event stream, opens and closes the task
modal on the Kanban three times, and returns to the view the tab was on; the modal is opened every probe so growth per
open shows, which an untouched tab would not.

It exits 1, naming each cause, when a probe row's p95 is over its budget or has no sample, when a sample or probe
fails (a server restart overlapping one does; three failed calls in a row end the run), or when a metric trends
upward: the lowest value of the run's last third sits above the lowest of its first
third by more than the metric's allowance (`ALLOWANCE` in the script). The lowest value ignores the sawtooth of
garbage collection and still catches a leak, which lifts it. A run under six samples is reported but not judged for
trends. `--report` holds every probe, sample, trend and failure as JSON.
