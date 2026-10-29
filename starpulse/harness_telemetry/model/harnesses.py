"""The harness configuration: the tiers an agent profile names and what each tier runs on a harness.

An agent is named by tier and effort (`@agent-standard-high`), never by model, so a page or a tracker stays
harness-agnostic. This file says, per harness, whether it can start a session, the model each tier runs on it and
which tiers take an effort. Callers that start a session resolve a profile here; the server hands the page `as_json()`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["Harness", "HarnessError", "Harnesses", "Tier", "load_harnesses"]


class HarnessError(ValueError):
    """The harness file is not one the view or a session start can run from."""


@dataclass(frozen=True)
class Tier:
    model: str
    efforts: tuple[str, ...]
    """The efforts this tier takes; empty when the harness gives it none."""
    models: dict[str, str] = field(default_factory=dict)
    """Optional per-effort model ids; when set, every effort must be named. Empty means use `model` for each."""
    run_efforts: dict[str, str] = field(default_factory=dict)
    """Optional per-effort session effort; when set, every effort must be named. Empty means run at the board effort."""

    def model_for(self, effort: str | None) -> str:
        """The model this effort runs: `models[effort]` when present, else `model`."""
        return self.models[effort] if effort and effort in self.models else self.model

    def run_effort(self, effort: str | None) -> str | None:
        """The effort a session for this board effort runs at: `run_efforts[effort]` when present, else `effort`."""
        return self.run_efforts.get(effort, effort) if effort else effort

    def as_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "efforts": list(self.efforts)}
        if self.models:
            body["models"] = dict(self.models)
        if self.run_efforts:
            body["run_efforts"] = dict(self.run_efforts)
        return body


@dataclass(frozen=True)
class Harness:
    name: str
    label: str
    sessions: bool
    """Whether a session can be started on this harness."""
    reason: str | None
    """Why it cannot, when `sessions` is false."""
    tiers: dict[str, Tier]

    def profiles(self) -> dict[str, tuple[str, str | None]]:
        """Each `@agent-<tier>[-<effort>]` profile and the `(model, effort)` it runs on this harness."""
        return {
            f"@agent-{name}-{effort}" if effort else f"@agent-{name}": (tier.model_for(effort), tier.run_effort(effort))
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
                    "tiers": {n: t.as_json() for n, t in h.tiers.items()},
                }
                for h in self.harnesses.values()
            ],
        }


def _names(value: object) -> tuple[str, ...] | None:
    ok = isinstance(value, list) and all(isinstance(item, str) and item for item in value)
    return tuple(value) if ok else None  # pyright: ignore[reportArgumentType]


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
        models = _per_effort(name, tier, "models", spec.get("models"), efforts)
        run_efforts = _per_effort(name, tier, "run_efforts", spec.get("run_efforts"), efforts)
        parsed[tier] = Tier(spec["model"], efforts, models, run_efforts)
    return Harness(name, raw.get("label", name), bool(sessions), reason, parsed)


def _per_effort(harness: str, tier: str, key: str, raw: object, efforts: tuple[str, ...]) -> dict[str, str]:
    """A per-effort table (`models` or `run_efforts`), or empty when the tier declares none."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and k and v for k, v in raw.items()
    ):
        raise HarnessError(f"harness {harness} tier {tier} {key} must be a table of effort = name")
    named = tuple(raw)
    if set(named) != set(efforts):
        raise HarnessError(
            f"harness {harness} tier {tier} {key} must name each effort "
            f"{', '.join(efforts) or 'none'}, not {', '.join(named) or 'none'}"
        )
    return {effort: raw[effort] for effort in efforts}


def load_harnesses(path: Path) -> Harnesses:
    """The harnesses `path` declares, or a `HarnessError` naming what is wrong."""
    raw = tomllib.loads(path.read_text())
    if not (tiers := _names(raw.get("tiers"))):
        raise HarnessError("tiers must be a non-empty list of names")
    return Harnesses(tiers, {name: _harness(name, spec, tiers) for name, spec in raw.get("harnesses", {}).items()})
