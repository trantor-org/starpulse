"""Hub ingest benchmark: N forwarders write event batches into one Postgres event log.

Measures what one hub sustains as instances forward events to it. Each writer process stands in for one IC forwarder posting a
batch; the insert is idempotent on ``event_id`` as the hub's ingest is.

Run this file with ``uv run python``, optionally passing a SQLAlchemy DSN; the
default expects a throwaway Postgres 17 on 127.0.0.1:55432 with password
``bench``, as ``docker run --rm -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=bench
postgres:17`` starts. The script drops and recreates ``starpulse_events`` there.
"""

import json
import statistics
import sys
import time
import uuid
from multiprocessing import Process, Queue

from sqlalchemy import Engine, create_engine, text

DSN = "postgresql+psycopg://postgres:bench@127.0.0.1:55432/postgres"
PAYLOAD = json.dumps(
    {
        "machine": "task",
        "task": "TASK-1234",
        "from": "In Progress",
        "to": "Review",
        "repo": "org/repo",
        "actor": "agent-7",
        "pad": "x" * 60,
    }
)
INSERT = (
    "INSERT INTO starpulse_events(instance, stream, event_id, fields) "
    "VALUES (%s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING"
)
# (writers, batches per writer, events per batch)
RUNS = [(10, 200, 1), (50, 100, 1), (50, 100, 50), (90, 20, 50), (90, 10, 200)]


def setup(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS starpulse_events"))
        c.execute(
            text(
                "CREATE TABLE starpulse_events("
                "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "instance text NOT NULL, stream text NOT NULL, event_id uuid NOT NULL UNIQUE, "
                "fields jsonb NOT NULL, at timestamptz NOT NULL DEFAULT now())"
            )
        )


def writer(dsn: str, out: Queue, batches: int, batch: int, instance: str) -> None:
    latencies = []
    with create_engine(dsn).connect() as c:
        for _ in range(batches):
            rows = [(instance, "machine", uuid.uuid4(), PAYLOAD) for _ in range(batch)]
            start = time.perf_counter()
            c.exec_driver_sql(INSERT, rows)
            c.commit()
            latencies.append((time.perf_counter() - start) * 1000)
    out.put(latencies)


def run(dsn: str, writers: int, batches: int, batch: int) -> None:
    out: Queue = Queue()
    start = time.time()
    procs = [Process(target=writer, args=(dsn, out, batches, batch, f"ic-{i}")) for i in range(writers)]
    for p in procs:
        p.start()
    latencies = sorted(lat for _ in procs for lat in out.get())
    for p in procs:
        p.join()
    elapsed = time.time() - start
    total = writers * batches * batch
    print(
        f"writers={writers:3d} batch={batch:3d} events={total:7d} {total / elapsed:8.0f} ev/s  "
        f"batch p50={statistics.median(latencies):.2f}ms p99={latencies[int(len(latencies) * 0.99)]:.2f}ms "
        f"max={latencies[-1]:.1f}ms"
    )


def main() -> None:
    dsn = sys.argv[1] if len(sys.argv) > 1 else DSN
    engine = create_engine(dsn)
    setup(engine)
    for writers, batches, batch in RUNS:
        run(dsn, writers, batches, batch)
    with engine.connect() as c:
        rows = c.execute(text("SELECT count(*) FROM starpulse_events")).scalar_one()
        size = c.execute(text("SELECT pg_total_relation_size('starpulse_events')")).scalar_one()
        start = time.perf_counter()
        c.execute(
            text("SELECT id FROM starpulse_events WHERE id > :cursor ORDER BY id LIMIT 1000"),
            {"cursor": rows - 500},
        ).fetchall()
        poll = (time.perf_counter() - start) * 1000
    print(f"rows={rows} bytes/row={size / rows:.0f} tail-poll={poll:.2f}ms")


if __name__ == "__main__":
    main()
