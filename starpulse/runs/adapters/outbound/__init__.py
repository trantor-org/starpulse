"""Outbound runs adapters, one module per scheduler."""

from starpulse.contracts.adapters import RunStatus


def node(name: str, depends: list[str], status: RunStatus, raw: str | None = None) -> dict:
    """A graph node of a `Dag` for an engine that declares no phase kind, precondition, lock or history."""
    return {"name": name, "depends": depends, "status": status, "raw": raw, "kind": None, "precondition": None, "lock": None, "last": []}


class Unreported:
    """A runs sink that drops what it is given, for a one-off read that reports nowhere."""

    def set_dags(self, *args: object) -> None:
        return
