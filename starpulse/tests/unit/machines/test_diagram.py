"""The static diagram a machine exports: Graphviz DOT a client renders without drawing the machine itself."""

from starpulse._internal.machines.diagram import dot

MACHINE = {
    "states": [
        {"id": "start", "name": "Start", "initial": True, "final": False},
        {"id": "done", "name": "Done", "initial": False, "final": True},
    ],
    "transitions": [
        {
            "source": "start",
            "target": "done",
            "event": "FINISH",
            "cite": {"skill": "completing-tasks", "quote": 'say "go"'},
        },
        {"source": "done", "target": "done", "event": "AGAIN"},
    ],
}


def test_each_state_is_a_node_and_each_transition_an_edge_labelled_by_its_event() -> None:
    drawn = dot("in-progress", MACHINE)

    assert drawn.startswith('digraph "in-progress" {')
    assert '"start" [label="Start"' in drawn
    assert '"start" -> "done" [label="FINISH"' in drawn
    assert '"done" -> "done" [label="AGAIN"]' in drawn


def test_the_initial_state_is_bold_and_a_final_state_double_ringed() -> None:
    drawn = dot("in-progress", MACHINE)

    assert '"start" [label="Start", penwidth=2]' in drawn
    assert '"done" [label="Done", peripheries=2]' in drawn


def test_a_citation_is_the_edges_tooltip_with_its_quotes_escaped() -> None:
    assert 'tooltip="completing-tasks: say \\"go\\""' in dot("in-progress", MACHINE)
