"""How the page names a workflow: `<instance>/<workflow>`, read from the config's domains."""

from collections.abc import Callable, Mapping, Sequence

__all__ = ["Qualify", "qualifier"]

#: Names a workflow as the page draws it. A machine or cue names its workflows by their own name; the page draws
#: them as `<instance>/<workflow>`, so what a machine says is read through one of these.
Qualify = Callable[[str], str]


def qualifier(domains: Mapping[str, Sequence[str]]) -> Qualify:
    """A workflow's own name as `<instance>/<workflow>`, when exactly one configured instance lists it.

    `domains` is the config's qualified domains. A name two instances list names neither of them, and a name
    no instance lists (`operator`, `agent`) is not a workflow, so both stay as they are.
    """
    owners: dict[str, set[str]] = {}
    for qualified in (name for names in domains.values() for name in names):
        owners.setdefault(qualified.partition("/")[2], set()).add(qualified)
    unique = {own: next(iter(names)) for own, names in owners.items() if len(names) == 1}
    return lambda name: unique.get(name, name)
