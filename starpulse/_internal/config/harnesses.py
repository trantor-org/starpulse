"""The harness configuration: the tiers an agent profile names and what each tier runs on a harness.

An agent is named by tier and effort (`@agent-standard-high`), never by model, so a page or a tracker stays
harness-agnostic. This file says, per harness, whether it can start a session, the model each tier runs on it and
which tiers take an effort, and optionally the SSH host and folder a Claude Desktop session opens on. Callers that start a
session resolve a profile here; the server hands the page `as_json()`.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["Desktop", "Harness", "HarnessError", "Harnesses", "Tier", "load_harnesses"]


class HarnessError(ValueError):
    """The harness file is not one the view or a session start can run from."""


@dataclass(frozen=True)
class Tier:
    model: str
    efforts: tuple[str, ...]
    """The efforts this tier takes; empty when the harness gives it none."""


@dataclass(frozen=True)
class Desktop:
    """Where a Claude Desktop SSH session opens: `user@address` and the folder on that host."""

    host: str
    folder: str


@dataclass(frozen=True)
class Harness:
    name: str
    label: str
    sessions: bool
    """Whether a session can be started on this harness."""
    reason: str | None
    """Why it cannot, when `sessions` is false."""
    tiers: dict[str, Tier]
    desktop: Desktop | None = None
    """The Desktop SSH host and folder, when the harness names one and its address variable is set."""

    def profiles(self) -> dict[str, tuple[str, str | None]]:
        """Each `@agent-<tier>[-<effort>]` profile and the `(model, effort)` it runs on this harness."""
        return {
            f"@agent-{name}-{effort}" if effort else f"@agent-{name}": (tier.model, effort)
            for name, tier in self.tiers.items()
            for effort in tier.efforts or (None,)
        }


@dataclass(frozen=True)
class Harnesses:
    tiers: tuple[str, ...]
    harnesses: dict[str, Harness]

    def as_json(self) -> dict[str, Any]:
        """What the page reads: the tiers in order and each harness with its models and efforts."""
        return {
            "tiers": list(self.tiers),
            "harnesses": [
                {
                    "name": h.name,
                    "label": h.label,
                    "sessions": h.sessions,
                    "reason": h.reason,
                    "tiers": {n: {"model": t.model, "efforts": list(t.efforts)} for n, t in h.tiers.items()},
                    "desktop": {"host": h.desktop.host, "folder": h.desktop.folder} if h.desktop else None,
                }
                for h in self.harnesses.values()
            ],
        }


def _names(value: object) -> tuple[str, ...] | None:
    ok = isinstance(value, list) and all(isinstance(item, str) and item for item in value)
    return tuple(value) if ok else None  # pyright: ignore[reportArgumentType]


def _desktop(name: str, raw: dict[str, Any]) -> Desktop | None:
    """The `desktop` table's host and folder. The address is read from the variable `host_env` names, so the file holds
    no address; an unset variable offers no Desktop session."""
    host_env, folder = raw.get("host_env"), raw.get("folder")
    if not host_env or not folder:
        raise HarnessError(f"harness {name} desktop needs host_env and folder")
    if not (address := os.environ.get(host_env, "")):
        return None
    user = raw.get("user")
    return Desktop(f"{user}@{address}" if user else address, folder)


def _harness(name: str, raw: dict[str, Any], tiers: tuple[str, ...]) -> Harness:
    sessions, reason = raw.get("sessions"), raw.get("reason")
    if not sessions and not reason:
        raise HarnessError(f"harness {name} cannot start a session, so it needs a reason")
    declared = raw.get("tiers", {})
    if tuple(declared) != tiers:
        raise HarnessError(
            f"harness {name} must define the tiers {', '.join(tiers)}, not {', '.join(declared) or 'none'}"
        )
    parsed = {}
    for tier, spec in declared.items():
        if not spec.get("model"):
            raise HarnessError(f"harness {name} tier {tier} needs a model")
        efforts = _names(spec.get("efforts", []))
        if efforts is None:
            raise HarnessError(f"harness {name} tier {tier} efforts must be a list of names")
        parsed[tier] = Tier(spec["model"], efforts)
    desktop = _desktop(name, raw["desktop"]) if "desktop" in raw else None
    return Harness(name, raw.get("label", name), bool(sessions), reason, parsed, desktop)


def load_harnesses(path: Path) -> Harnesses:
    """The harnesses `path` declares, or a `HarnessError` naming what is wrong."""
    raw = tomllib.loads(path.read_text())
    if not (tiers := _names(raw.get("tiers"))):
        raise HarnessError("tiers must be a non-empty list of names")
    return Harnesses(tiers, {name: _harness(name, spec, tiers) for name, spec in raw.get("harnesses", {}).items()})
