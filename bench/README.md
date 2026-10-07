# Benchmarks

Three scripts measure the event log at the two ends of a deployment and the reads of the store beside it. They are
not part of the installed package and the test suite does not run them.

| Script | Measures | Needs |
| --- | --- | --- |
| `hub_ingest.py` | N forwarder processes writing event batches into one Postgres event log; the insert is idempotent on `event_id`, as a hub's ingest is | a throwaway Postgres 17 |
| `ic_event_log.py` | concurrent fail-open appends to an instance's SQLite WAL log while a reader polls by cursor, at 10 thousand and 1 million rows | a scratch file path |
| `flow_reads.py` | the p95 of flow health, the level and its trajectories over a SQLite store of 10 thousand, 1 million and 10 million lane changes, read from the summaries the store keeps on write | a scratch directory with room for about 6 GB |

Run them from the repository root after `uv sync`.

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
by up to 1.5x on the 6 to 15 ms health read and by 1.2x on the level, in both directions, with no trend in the size. Each read sends 5 or 7 statements at every size
and none touches `starpulse_machine_events` or `starpulse_lane_changes`. Before the summaries the same reads folded
every lane change: at 1 million, health took 9.2 s and the level 11.6 s (p95 of 3 reads, wall). At 10 thousand the
level reads the whole history, because the trailing 12 weeks that set the aging threshold reach back past its start;
that is the most it ever reads, and why the level's cost stays where it is as the history grows. Loading 10 million
lane changes took about a minute and `rebuild_summaries` about 6 minutes.

Rates depend on the host, so compare runs on the same machine.
