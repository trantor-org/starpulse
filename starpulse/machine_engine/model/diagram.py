"""A machine as a static Graphviz DOT diagram, so a client renders it without drawing the machine itself."""

from typing import Any

__all__ = ["dot"]


def dot(name: str, machine: dict[str, Any]) -> str:
    """The DOT source for `machine` as `snapshot.describe` draws it: a node per state, an edge per transition.

    The initial state is bold and a final one double-ringed; an edge is labelled by its event and, when its YAML
    cites a skill sentence, carries it as the tooltip.
    """
    lines = [f"digraph {_quote(name)} {{", "  rankdir=LR;"]
    for state in machine["states"]:
        style = ", penwidth=2" if state["initial"] else ", peripheries=2" if state["final"] else ""
        lines.append(f"  {_quote(state['id'])} [label={_quote(state['name'])}{style}];")
    for transition in machine["transitions"]:
        attributes = f"label={_quote(transition['event'])}"
        if cite := transition.get("cite"):
            attributes += f", tooltip={_quote(cite['skill'] + ': ' + cite['quote'])}"
        lines.append(f"  {_quote(transition['source'])} -> {_quote(transition['target'])} [{attributes}];")
    return "\n".join([*lines, "}"]) + "\n"


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
