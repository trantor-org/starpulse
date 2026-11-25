"""The time one agent verb spends in each step, posted to the server's `POST /api/steps`; a post that fails is dropped."""

import time
from collections.abc import Generator
from contextlib import contextmanager

from starpulse.cli import agent_wire


@contextmanager
def timed(command: str, base: str) -> Generator[dict[str, float]]:
    """Yield the dict a verb adds its step seconds to; leaving the block posts them, `failed` when it raised."""
    steps: dict[str, float] = {}
    outcome = "ok"
    try:
        yield steps
    except BaseException:
        outcome = "failed"
        raise
    finally:
        try:
            agent_wire.post(base, "/api/steps", {"command": command, "outcome": outcome, "steps": steps})
        except Exception:  # noqa: BLE001 - the times are advisory: a server that refuses them never fails the verb
            pass


@contextmanager
def step(steps: dict[str, float], name: str) -> Generator[None]:
    """Add the seconds the block takes to `steps[name]`, a block that raised included."""
    started = time.perf_counter()
    try:
        yield
    finally:
        steps[name] = steps.get(name, 0.0) + time.perf_counter() - started
