# Build a consumer

StarPulse produces events and records; it does not own what you do with them. A consumer, such as a dashboard feed,
an alert or a report, reads the export contract and keeps its own store:

- `starpulse.event_log`: `Tail` reads the event log, one cursor per reader.
- `starpulse.contracts`: the record of every stream, as a pydantic model (`CONTRACTS`) and a JSON Schema
  (`SCHEMAS`, checked in under `starpulse/schemas/`), and `EVENT_STREAMS`, which names the contract of each stream.
- The `starpulse` command line's reads.

A consumer never reads the history store's tables, a board's files or a private stream: those change without notice.
When a consumer needs a field the contract lacks, the field is added to the contract.

## Streams

| Stream | Contract | One entry is |
|---|---|---|
| `machine:events` | `machine-events` (`MachineEvent`) | a lifecycle machine's event for a task or run |
| `board:lanes` | `lane-events` (`LaneEvent`) | a task entering a Board lane, with its team, milestone and labels |
| `runs:events` | `run-events` (`RunEvent`) | a workflow run, or one of its steps, starting or ending |

A package test fails when a producer declares a stream that `EVENT_STREAMS` lacks, and when an entry a producer writes
does not validate against its stream's schema. An `Entry`'s `fields` are the record: `Entry.event_id` is the entry's
idempotency key, `Entry.at` is when the log took it, and `Entry.id` is the cursor to resume after. The records here are
those of an instance's log; a hub's log adds `source` (and, for a run, `instance`) to what it receives.

## The pattern

Tail the streams you read, write each entry into your own store, and keep the cursor in that store, in the same
transaction as the rows. Then a crash between the two loses neither, and a restart resumes where the sink stopped,
without a cursor file of its own to lose.

```python
import sqlite3

from starpulse.contracts import CONTRACTS, EVENT_STREAMS
from starpulse.event_log import EventLog, Tail

READER = "my-sink"  # names this reader in the log's gap records


def open_sink(path: str) -> sqlite3.Connection:
    sink = sqlite3.connect(path)
    sink.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, stream TEXT NOT NULL, at REAL NOT NULL, record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cursor (reader TEXT PRIMARY KEY, after_id INTEGER NOT NULL);
        """
    )
    return sink


def drain(log: EventLog, sink: sqlite3.Connection) -> int:
    """Copy what the log gained since the last call into `sink`; return how many entries it read."""
    kept = sink.execute("SELECT after_id FROM cursor WHERE reader = ?", (READER,)).fetchone()
    tail = Tail(log, READER, after=kept[0] if kept else None, streams=sorted(EVENT_STREAMS))
    read = 0
    while entries := tail.poll():
        with sink:  # the rows and the cursor commit together
            for entry in entries:
                record = CONTRACTS[EVENT_STREAMS[entry.stream]].model_validate(entry.fields)
                sink.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?)",
                    (entry.event_id, entry.stream, entry.at, record.model_dump_json()),
                )
            sink.execute("INSERT OR REPLACE INTO cursor VALUES (?, ?)", (READER, tail.cursor))
        read += len(entries)
    return read
```

Call `drain` from a timer, a cron job or a loop; a call with nothing new costs one indexed query.

- **Open the log with the database URL.** `EventLog("sqlite:///starpulse-history.sqlite")`, or the Postgres URL the
  config's `database_url` names. Many processes append and read the same file: the log runs in WAL mode.
- **At least once.** A crash after the log handed over a row but before the commit reads it again, so key the sink on
  `event_id`, as `INSERT OR IGNORE` does above.
- **Retention.** `serve` prunes rows older than `event_log_retention_days` and archives them first (see the event log
  archive in [Serve and configure](serving.md)). A cursor older than the oldest retained row resumes at that row and the
  log notes the span you missed in `starpulse_gaps`; start a new sink from the archive when you need that span.
- **A resident reader.** `Tail.run(handle, stop)` polls until `stop` is set and passes each entry to `handle`; pass the
  exceptions that mean your sink is down as `transient` so the entry is retried instead of skipped.
- **A record that fails validation** raises out of `drain` before anything commits, so the sink never holds a
  record the contract rejects. Report it: the package's own producers write only valid records.

## Query the sink

Your store is plain SQL, so the dashboards it feeds are yours to shape. Here, how many tasks entered each lane:

```sql
SELECT json_extract(record, '$.lane') AS lane, COUNT(*) AS entries
FROM events
WHERE stream = 'board:lanes'
GROUP BY lane;
```
