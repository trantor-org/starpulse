"""What `serve` and the workers it supervises build their collaborators from: the config, the run adapters, the
page build and the checks made before anything starts."""

import argparse
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
from starpulse.runs.model import opt_in
from starpulse.runs.model.config import RunsInstance
from starpulse.runtime.config import Config, ConfigError, discover, load, runs_adapter

logger = logging.getLogger(__name__)


_HERE = Path(__file__).parents[1]


#: The Vite build of web/; it holds nothing but the page, so all of it is served. `STARPULSE_STATIC` names another
#: directory; the environment reaches the child workers a fresh interpreter starts, where a patched attribute would not.
STATIC = Path(os.environ.get("STARPULSE_STATIC") or _HERE / "static")


def read_config(parser: argparse.ArgumentParser, path: Path | None) -> Config:
    """The config in `path`, else `starpulse.toml` beside where the view runs, else the defaults."""
    path = discover(path)
    try:
        return load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")


def _adapter(parser: argparse.ArgumentParser, instance: RunsInstance) -> ModuleType:
    """The runs adapter module of `instance`: `start(url)` gives its start capability or None, `follow(url, sink, log)` reads its workflows from the event log and the instance."""
    try:
        return runs_adapter(instance.type)
    except ConfigError as exc:
        parser.exit(1, f"runs instance {instance.name}: {exc}\n")


def run_adapters(parser: argparse.ArgumentParser, config: Config) -> list[tuple[RunsInstance, ModuleType]]:
    """Each `[[runs]]` instance that names a type, with its adapter module (an instance with none is push-only)."""
    return [(instance, _adapter(parser, instance)) for instance in config.runs if instance.type]


def announce(port: int) -> None:
    """Say on the terminal where the view is."""
    print(f"StarPulse on :{port}", flush=True)


class Prepared(NamedTuple):
    """What the config and the environment settle before anything starts: `serve` fails on it before it spawns a child,
    and the Page API is built from it."""

    producer_tokens: dict[str, str]
    opt_in_workers: list[str]
    """The `[[runs]]` instances an adapter's own worker runs (`starpulse.runs.model.opt_in`): `serve` runs none of them itself."""


def export_github_token(config: Config) -> None:
    """Export the token `github_token_env` names as `GITHUB_TOKEN` and `GH_TOKEN`, so the GitHub reads and every worker
    sign in with it; `gh` reads `GH_TOKEN` first, which systemd's `EnvironmentFile=` may leave a literal `$VAR` alias.
    Unset, or the variable unset, both are left as they were."""
    token = os.environ.get(config.github_token_env or "")
    if token:
        os.environ["GITHUB_TOKEN"] = os.environ["GH_TOKEN"] = token


def prepare(parser: argparse.ArgumentParser, args: argparse.Namespace, config: Config) -> Prepared:
    """Check `config` and the environment for serving, exiting with the reason when they cannot serve."""
    try:
        producer_tokens = ingest_tokens(config.producers, os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    if config.webhook_producer and not os.environ.get(config.webhook_token_env or ""):
        parser.exit(1, f"webhook_token_env: {config.webhook_token_env} is not set\n")
    if not (STATIC / "index.html").is_file():
        parser.exit(1, f"{STATIC} has no build; run `pnpm --filter @starpulse/web build` first\n")
    adapters = run_adapters(parser, config)
    opted_in = [instance.name for instance, adapter in adapters if opt_in.worker_of(adapter)]
    return Prepared(producer_tokens, opted_in)
