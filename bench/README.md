# Benchmarks

Three scripts measure the event log at the two ends of a deployment and the reads of the store beside it, a fourth
times a running page against its latency budget, a fifth holds that page open idle to see it degrade, and a sixth loads
it with many viewers at once. They are not part of the installed package and the test suite does not run them;
`ci/test_page_latency.py`, `ci/test_soak.py` and `ci/test_load.py` hold the page harnesses' rules.

| Script | Measures | Needs |
| --- | --- | --- |
| `hub_ingest.py` | N forwarder processes writing event batches into one Postgres event log; the insert is idempotent on `event_id`, as a hub's ingest is | a throwaway Postgres 17 |
| `ic_event_log.py` | concurrent fail-open appends to an instance's SQLite WAL log while a reader polls by cursor, at 10 thousand and 1 million rows | a scratch file path |
| `flow_reads.py` | the p95 of flow health, the level and its trajectories over a SQLite store of 10 thousand, 1 million and 10 million lane changes, read from the summaries the store keeps on write | a scratch directory with room for about 6 GB |
| `page_latency.py` | the p50 and p95 of every read route, the event stream's first snapshot, and in Chrome the first paint (navigation to the frame that draws the board), each view switch, a task modal, the Star Map's fly-to, each stream event to paint and the page's frames, against 50 ms (16.7 ms a frame) | a running StarPulse and Google Chrome |
| `soak.py` | one tab held open for hours: every 10 minutes the budget probed and the task modal opened and closed, every few minutes the JS heap, DOM nodes, listeners, idle frames per second, and the server's RSS, threads and open files; against a running StarPulse, or a seeded one it starts and feeds events | Google Chrome, a built page for the seeded server, or a running StarPulse |
| `load.py` | a Locust crowd of viewers, each holding the event stream open and reading the `/api` routes: per-route p50, p95 and p99 and the stream's first snapshot, against 50 ms | a running StarPulse |

Run them from the repository root after `uv sync`; `page_latency.py`, `soak.py` and `load.py` also need `uv sync --group bench`.

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

**When to run.** After any change to a summarised read, rerun `flow_reads.py` at 10 thousand and 1 million events.

The script records synthetic Board lane changes at a fixed rate (about 125 a day) into a SQLite store, summarises
them as the store does at start-up, and asks `/api/analytics/health`, `/api/level` and `/api/level/trajectories`
for the default week 60 times each. It prints the p95 in wall and CPU time with the statements each read sends, and
exits 1 when the CPU p95 at any size is over 2x the first size's. `--scan N` also times the whole-table reads the
summaries replaced, on the stores up to N events.

Result (ai-vm-1, SQLite, 60 reads each; CPU time judges the 2x gate):

| Events | Health p95 (wall / CPU) | Level p95 (wall / CPU) | Trajectories p95 (wall / CPU) | Store |
| ---: | --- | --- | --- | ---: |
| 10 thousand | 3.8 / 3.8 ms | 135.5 / 135.5 ms | 213.1 / 175.7 ms | 3 MB |
| 1 million | 3.9 / 3.9 ms (x1.05) | 145.7 / 145.7 ms (x1.08) | 165.4 / 165.2 ms (x0.94) | 289 MB |
| 10 million | 3.7 / 3.8 ms (x0.99) | 68.5 / 67.6 ms (x0.50) | 106.0 / 104.4 ms (x0.59) | 3.0 GB |

The ratios are the CPU p95 against the 10 thousand row, all under 2x. Health sends six statements at every size and
fetches 29, 37 and 45 rows: rows for the lanes and tasks in flight, not every lane interval. None of the reads touches
`starpulse_machine_events` or `starpulse_lane_changes`. Before the summaries the same reads folded every lane change:
at 1 million, health took 9.2 s and the level 11.6 s (p95 of 3 reads, wall). At 10 thousand the level reads the whole
history, because the trailing 12 weeks that set the aging threshold reach back past its start; that is the most it
ever reads, and why the level's cost stays where it is as the history grows. Loading 10 million lane changes took
69.5 seconds and `rebuild_summaries` took 289.9 seconds.

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
CPU over `STARVED_SHARE` (0.25%) of the run, it ends the table with a `STARVED` line, sets `starved` in the JSON and
exits 2, neither a pass nor a failure: its rows measure the host's load, not the page. The share is that small because
a modal open is two frames, so one late frame puts it over budget: runs at load1 9 to 20 on a 36-core host waited 0.03%
to 0.11% and opened every modal on time, and runs that waited 0.48% and up stalled opens for 250 ms and longer.

`--cpu-throttle N` slows the page's CPU N times once the board has painted (Chrome's `Emulation.setCPUThrottlingRate`), so
a view switch, a stream event and a modal are timed on a machine N times slower than the bench's, as a viewer's laptop
draws them. The first-paint row stays unthrottled. Pair it with `--viewer`:

```sh
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766 --assets .tmp/page-build --viewer --cpu-throttle 4
```

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
`--judge KIND` (repeatable; `request`, `connect`, `stream`, `interaction`, `frame`) judges only the rows of those kinds:
the rest print with a `not judged` note and never fail the run, for a host whose CPU cannot hold the page's paint and
interaction rows but can hold its routes and stream deliveries. An untimed request still fails the run.

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

A probe runs before the sample due at the same moment, so the first sample is of a page that has visited the views a
probe visits; sampled before them, its floor sits under every later one and reads as a rise.

### Seeded server

```sh
pnpm --dir starpulse/web install --frozen-lockfile && pnpm --dir starpulse/web run build   # once: the server serves the built page
uv run --group bench python bench/soak.py --duration 4h --report .tmp/soak.json
uv run --group bench python bench/soak.py --duration 100s --interval 30s --sample-every 15s --report .tmp/soak.json
```

Without a URL the soak starts `ci/seeded_server.py` itself: on a free port, in a scratch directory it removes on the
way out, as its own child. The server is the process the samples read `/proc` for, so every sample carries the one pid
for the whole run, and a server that exits is a failure of the run. The tab, the probes, the samples and the trend rule
are the ones above. A static seeded board sends the tab nothing, so the server also replays an event stream: it moves
the seeded tasks that are In Progress or in Review to the other lane, one `task` event on every open stream a move,
until the run ends.

- `--replay-multiple N`: the replay rate as a multiple of the live rate (default 6). Seeded server only.
- `--ceiling "ROW=MS"`: hold a probe row to MS instead of 50, as `page_latency.py --ceiling` does, and name it in the
  report's `ceilings`. For a host whose hardware cannot hold a row: ai-vm-1's Xeon opens a task's modal in 50 to 300 ms
  under its usual load. The default holds every row to the budget, which is what the Tower runner's hold is judged by.
- A URL selects a running server and takes `--pid`; `--replay-multiple` is refused with one, and `--pid` without one.

**Replay rate.** The live instance's event log took 14,497 events in the 24 hours to 2026-10-10 09:30 MST, 1,312 of
them lane changes, and 11,075 a day over the 7 days before. `LIVE_EVENTS_PER_DAY` in `soak.py` is 14,500, about 0.17
events a second. The default is 6 times that, 1.007 events a second, because a 4 hour hold is a sixth of a day: 14,500
events pass through the tab, a day of the live instance's. A longer hold at the default replays proportionally more
(24 hours is 6 days), and `--replay-multiple 1` is the live rate. The replay is a stream of lane moves; it does not
replay pull request, workflow or Ledger changes, so those payloads are not exercised. The report's `replay` holds the
multiple, its events a second and the events the server sent (a 100 second run sent 103).

## Load

```sh
uv run --group bench locust -f bench/load.py --host http://127.0.0.1:8766 --headless -u 50 -r 5 -t 2m
uv run --group bench locust -f bench/load.py --host http://127.0.0.1:8766
```

`page_latency.py` times one viewer; this times the same budget under a crowd. Each Locust user is one open page: it
holds `/api/events?snapshot=ref` open, reads the snapshot body its first event names, then reads a random `/api` route
from `page_latency.py`'s `READS` every 0.5 to 2 seconds. The first viewer probes every route once (the `discovery`
row, not judged) and skips one that does not answer 200, as the seeded server's milestones and docs do not; the
viewers that spawn meanwhile wait for its answer. The body row (`/api/events/body/<id>`) asks for gzip and leaves the
body compressed: a viewer's browser inflates it on the viewer's machine, and inflating a crowd's bodies in Locust's
one process timed that process, not the server. `-u` is
the crowd, `-r` how many join a second, `-t` the run; without `--headless` Locust serves its web UI on port 8089 and
charts the crowd live. `--what-if FROM TO` is `page_latency.py`'s (`in_progress review` on `ci/seeded_server.py`).

At the end Locust prints each route's p50 to p100 and `/api/events first snapshot`, connect to the end of the
stream's first `snapshot` event. The run exits 1, printing an `OVER BUDGET` line per cause, when a route's p95 is over
50 ms or one of its requests failed. Every viewer holds a server thread for its stream, so a high `-u` also measures
how the server shares its threads; host load moves the tail as it does `page_latency.py`'s.
