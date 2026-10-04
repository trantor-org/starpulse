# StarPulse

StarPulse draws the flow of work: the workflows your scheduler runs, the lifecycle machines your tasks move
through, and the agents and people moving them, live in one page.

## Run it

```sh
uvx --from git+https://github.com/trantor-org/starpulse starpulse serve
```

StarPulse reads its streams from Redis: set `REDIS_URL` (or `<PREFIX>_REDIS_HOST`, `_PORT` and
`REDIS_PASSWORD`). With no config file it draws the [Backlog.md](https://github.com/MrLesk/Backlog.md) project in
`./backlog` and keeps its history in `starpulse-history.sqlite` beside it.

## Configure it

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read
when it exists. Credentials never go in it.

```toml
tracker_url = "https://tracker.example.com"
# History in Postgres instead of SQLite (install the `postgres` extra: `starpulse[postgres]`).
database_url = "postgresql+psycopg://db.example.com/starpulse"

# The board adapter: a module under `starpulse`, or a dotted path to one an installed package provides.
# The rest of the table is that adapter's settings.
[board]
type = "upstream_backlog"

# A runs adapter instance; its workflows are drawn as `<name>/<workflow>`.
[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.example.com:8080"
run_safe = ["nightly"]
domains = { Data = ["nightly", "etl"] }
```

A board adapter is a module whose `board(settings, base)` returns a `starpulse.board.Board`: the machines the page
draws, how the Board's tasks are placed, and optionally a writer for moves made on the page.

## Report runs from any scheduler

```sh
starpulse emit start --workflow nightly --run 2026-10-03 --status running
starpulse emit end   --workflow nightly --run 2026-10-03 --status succeeded --step load --depends fetch
```

A workflow no adapter lists is drawn from the step graph its `emit` calls add up to.

## Develop

```sh
uv sync
uv run pytest            # integration tests start Redis and Postgres containers, so Docker must run
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build   # builds the page into starpulse/static
```

## License

MIT; see [LICENSE](LICENSE).
