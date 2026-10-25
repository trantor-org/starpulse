"""One table places an event leniently (the machine level) or strictly (the replay judge), and the graph agrees with the strict rule."""

from pathlib import Path

from starpulse.machine_engine.model.graph import Violation, conform, replay
from starpulse.machine_engine.model.machine_definition import compile_document
from starpulse.machine_engine.model.snapshot import describe
from starpulse.machine_engine.model.transitions import Table
from starpulse.tests.unit.machine_engine.test_graph import FLOW

#: Done is final, so the last SUBMIT begins again from `start`, which no SUBMIT leaves.
TRACE = ["OPEN", "SUBMIT", "APPROVE", "SUBMIT"]


def test_one_trace_is_placed_by_the_lenient_rule_the_strict_rule_and_the_graph() -> None:
    chart = compile_document(FLOW, Path("flow.yaml")).machine
    table = Table(describe(chart))

    lenient = strict = frozenset()
    placed_lenient, placed_strict = [], []
    for event in TRACE:
        lenient = table.place(lenient, event, lenient=True)
        strict = table.place(strict, event, lenient=False)
        placed_lenient.append(lenient)
        placed_strict.append(strict)

    assert placed_lenient == [{"draft"}, {"review"}, {"done"}, {"review"}]
    assert placed_strict == [{"draft"}, {"review"}, {"done"}, set()]
    assert conform(chart, TRACE) == Violation(3, "SUBMIT", frozenset({"done"}))
    assert [step.legal for step in replay(chart, TRACE)] == [True, True, True, False]
