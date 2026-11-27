# Benchmarks

Two scripts measure the event log and the reads of the store beside it, a third times a running page against its
latency budget, a fourth holds that page open idle to see it degrade, and a fifth loads it with many viewers at once. They are not part of the installed package and the test suite does not run them;
`ci/test_page_latency.py`, `ci/test_soak.py` and `ci/test_load.py` hold the page harnesses' rules.

| Script | Measures | Needs |
| --- | --- | --- |
| `ic_event_log.py` | concurrent fail-open appends to an instance's SQLite WAL log while a reader polls by cursor, at 10 thousand and 1 million rows | a scratch file path |
| `page_latency.py` | the p50 and p95 of every read route, the `health` subscription's first event, and in Chrome the first paint (navigation to the frame that draws the board), each view switch, a task modal, the Star Map's fly-to, each `/graphql` subscription's frame to paint (a row per subscription) and the page's frames, against 50 ms (16.7 ms a frame) | a running StarPulse and Google Chrome |
| `soak.py` | one tab held open for hours: every 10 minutes the budget probed and the task modal opened and closed, every few minutes the JS heap, DOM nodes, listeners, idle frames per second, and the server's RSS, threads and open files; against a running StarPulse, or a seeded one it starts and feeds events | Google Chrome, a built page for the seeded server, or a running StarPulse |
| `load.py` | a Locust crowd of viewers, each holding the `health` subscription open and reading the `/api` routes: per-route p50, p95 and p99 and the subscription's first event, against 50 ms | a running StarPulse |

Run them from the repository root after `uv sync`; `page_latency.py`, `soak.py` and `load.py` also need `uv sync --group bench`.

## Instance event log

```sh
uv run python bench/ic_event_log.py .tmp/bench-events.db
```

The script replaces the file it is given, along with its `-wal` and `-shm` files. Each append opens a fresh
connection, as a short-lived writer process does. It prints one line per table size: appends per second, the
append and cursor-poll p50 and p99, and the database size.

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
draws them. The first-paint row stays unthrottled, and its samples start after one discarded navigation so Chromium's
process start is not counted as the page. Pair it with `--viewer`:

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
record (`/api/task/<id>`) reads the first one the task query (`POST /graphql`) lists; the task list and the task detail are timed as `/graphql tasks` and `/graphql task` rows; a route the server does not
serve reports its status in the row's note. Wall-clock times on a busy host carry its load: run it more than once
before reading one slow row as a regression.

`--repeat N` times every surface N times and judges each row on the median run's p95 (the lower median for an even
count), so one starved run on a loaded runner neither fails a row nor hides a slow one; the row's note lists every
run's p95.
`--ceiling "ROW=MS"` holds a row with a known overrun to MS instead of 50: the row still fails past it and its note
says it is over the budget until its fix lands. The gate holds the first paint of the board at 120 ms (79 ms p95 on a
quiet slot) until page work cuts it; drop the flag then.
`--judge KIND` (repeatable; `request`, `connect`, `stream`, `interaction`, `frame`) judges only the rows of those kinds:
the rest print with a `not judged` note and never fail the run, for a host whose CPU cannot hold the page's paint and
interaction rows but can hold its routes and stream deliveries. An untimed request still fails the run.
`--fail-non-2xx` fails the run when a judged request row answered with a non-2xx status (the row still notes
`answered [...]` without the flag).

## Latency gate

Trantor's nightly `starpulse-latency` Temporal command job runs `ci/latency_gate.sh` against main; pull requests do not, because on the shared `validate` lane it was the slowest job and
red from host load alone. It builds the page, serves `ci/seeded_server.py` (`ci/preview.toml`'s workspace with the real
request handler, a month of lane history for about 160 tasks, a level, 16 milestones and 24 docs on a native board,
and an scheduler with one capacity sample), runs `page_latency.py --repeat 3 --fail-non-2xx` against it with two ceilings (the board's first paint at 450 ms, and the main-thread row at 250 ms because the page's startup JavaScript is one 50-85 ms task on every load)
and fails on a row over budget, a non-2xx request row, or an untimed request. `ci/seeded_server.py` runs the same server by hand:

```sh
uv run python -m ci.seeded_server --port 8766 --dir .tmp/gate
uv run --group bench python bench/page_latency.py http://127.0.0.1:8766 --repeat 3
```

The seeded board is smaller than a live one: a cost that grows with the board is the manual [soak](#soak)'s to find: no nightly job runs it, and the nightly latency job will not catch one.

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
  report's `ceilings`. For a host whose hardware cannot hold a row: the build host's Xeon opens a task's modal in 50 to 300 ms
  under its usual load. The default holds every row to the budget, which is what the soak runner's hold is judged by.
- A URL selects a running server and takes `--pid`; `--replay-multiple` is refused with one, and `--pid` without one.

No schedule runs this mode: start it by hand for 4 hours against main's tip, and `release.yml` does not soak a tag. The
seeded server's scratch directory is removed when the run exits; the report stays where `--report` names it
(`.tmp/soak.json` above).

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
holds the `health` subscription (a POST to `/graphql`) open, then reads a random `/api` route
from `page_latency.py`'s `READS` and `GRAPHQL` (a POST to `/graphql`) every 0.5 to 2 seconds. The first viewer probes every route once (the `discovery`
row, not judged) and skips one that does not answer 200, as a server with no milestones, docs or scheduler does not; the
viewers that spawn meanwhile wait for its answer. Every judged read asks for gzip and leaves the body compressed: a viewer's browser inflates it on the viewer's
machine, and inflating a crowd's bodies in Locust's one process timed that process, not the server (the 5 MB
`/api/snapshot` takes about 28 ms of the one thread every viewer shares). `-u` is
the crowd, `-r` how many join a second, `-t` the run; without `--headless` Locust serves its web UI on port 8089 and
charts the crowd live.

At the end Locust prints each route's p50 to p100 and `/graphql health first event`, connect to the end of the
subscription's first event. The run exits 1, printing an `OVER BUDGET` line per cause, when a route's p95 is over
50 ms or one of its requests failed. Every viewer holds a server thread for its stream, so a high `-u` also measures
how the server shares its threads; host load moves the tail as it does `page_latency.py`'s.
