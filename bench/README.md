# Benchmarks

Two scripts measure the event log at the two ends of a deployment. They are not part of the installed
package and the test suite does not run them.

| Script | Measures | Needs |
| --- | --- | --- |
| `hub_ingest.py` | N forwarder processes writing event batches into one Postgres event log; the insert is idempotent on `event_id`, as a hub's ingest is | a throwaway Postgres 17 |
| `ic_event_log.py` | concurrent fail-open appends to an instance's SQLite WAL log while a reader polls by cursor, at 10 thousand and 1 million rows | a scratch file path |

Run both from the repository root after `uv sync`.

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

Rates depend on the host, so compare runs on the same machine.
