"""A stateDiagram-v2 file drafts a machine definition that validates, compiles and re-renders to the same diagram."""

from pathlib import Path

import pytest
import yaml

from starpulse._internal.domain import mermaid_import
from starpulse._internal.domain.machine_definition import MachineDefinitionError, validate
from starpulse._internal.domain.mermaid_import import Diagram, draft_machine, parse

SAMPLE = """\
%% comment
stateDiagram-v2
    direction TB
    state "Open" as open
    state "Closed" as closed
    [*] --> open
    closed --> [*]
    open --> closed : Close it [can_close]
    open --> open : Touch
    closed --> open
"""


def _shape(diagram: Diagram) -> tuple[set[str], str | None, set[str], list[tuple[str, str, str]]]:
    """A diagram without its declaration order, which a machine's event grouping reorders."""
    edges = sorted((e.source, e.target, e.label or "") for e in diagram.transitions)
    return set(diagram.states), diagram.initial, set(diagram.final), edges


class TestParse:
    def test_reads_states_markers_and_transitions(self) -> None:
        diagram = parse(SAMPLE)

        assert diagram.states == ["open", "closed"]
        assert diagram.initial == "open"
        assert diagram.final == ["closed"]
        assert [(t.source, t.target, t.label) for t in diagram.transitions] == [
            ("open", "closed", "Close it"),
            ("open", "open", "Touch"),
            ("closed", "open", None),
        ]

    def test_a_state_only_named_by_a_transition_is_declared(self) -> None:
        assert parse("stateDiagram-v2\n  [*] --> a\n  a --> b : Go\n").states == ["a", "b"]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("flowchart TD\n  a --> b\n", "not a stateDiagram-v2 file: its first line must be `stateDiagram-v2`"),
            ("", "not a stateDiagram-v2 file: its first line must be `stateDiagram-v2`"),
            ("%% only a comment\n", "not a stateDiagram-v2 file: its first line must be `stateDiagram-v2`"),
            ("stateDiagram-v2\n  a --> b : Go\n", "the diagram has no initial state: add `[*] --> <state>`"),
            (
                "stateDiagram-v2\n  [*] --> a\n  [*] --> b\n  a --> b : Go\n",
                "line 3: a machine has one initial state, found a second",
            ),
            (
                "stateDiagram-v2\n  [*] --> a\n  a : a note line\n",
                "line 3: unsupported stateDiagram syntax: 'a : a note line'",
            ),
            (
                "stateDiagram-v2\n  [*] --> Open\n",
                "'[*] --> Open': state id 'Open' must be lowercase letters, digits and _",
            ),
            (
                "stateDiagram-v2\n  [*] --> a\n  Open --> [*]\n",
                "'Open --> [*]': state id 'Open' must be lowercase letters, digits and _",
            ),
            (
                "stateDiagram-v2\n  [*] --> a\n  Open --> b : Go\n",
                "'Open --> b : Go': state id 'Open' must be lowercase letters, digits and _",
            ),
            (
                "stateDiagram-v2\n  [*] --> a\n  a --> Open : Go\n",
                "'a --> Open : Go': state id 'Open' must be lowercase letters, digits and _",
            ),
            (
                'stateDiagram-v2\n  [*] --> a\n  state "Open" as Open\n',
                "'state \"Open\" as Open': state id 'Open' must be lowercase letters, digits and _",
            ),
        ],
        ids=[
            "not a state diagram",
            "empty file",
            "comment only",
            "no initial state",
            "two initial states",
            "unsupported line",
            "bad initial id",
            "bad final id",
            "bad source id",
            "bad target id",
            "bad declared id",
        ],
    )
    def test_refuses_what_it_cannot_draft(self, text: str, message: str) -> None:
        with pytest.raises(MachineDefinitionError) as refused:
            parse(text)

        assert str(refused.value) == message

    def test_the_older_header_without_v2_is_accepted(self) -> None:
        assert parse("stateDiagram\n  [*] --> a\n").initial == "a"

    def test_a_blank_line_and_a_comment_before_the_header_are_skipped(self) -> None:
        assert parse("\n%% note\n\nstateDiagram-v2\n  [*] --> a\n").initial == "a"


class TestDraftMachine:
    def test_events_come_from_labels_and_guards_are_left_out(self) -> None:
        draft = draft_machine("sample", parse(SAMPLE))

        assert draft == {
            "name": "sample",
            "states": {"open": {"initial": True}, "closed": {"final": True}},
            "events": {
                "CLOSE_IT": [{"from": "open", "to": "closed"}],
                "TOUCH": [{"from": "open", "to": "open"}],
                "CLOSED_TO_OPEN": [{"from": "closed", "to": "open"}],
            },
        }

    def test_one_label_on_several_edges_is_one_event(self) -> None:
        text = "stateDiagram-v2\n  [*] --> a\n  a --> b : Archive\n  b --> c : Archive\n"

        assert draft_machine("m", parse(text))["events"] == {
            "ARCHIVE": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]
        }

    @pytest.mark.parametrize(
        ("label", "event"),
        [
            ("Go!", "GO"),
            ("-- go on --", "GO_ON"),
            ("a", "A"),
            ("A1", "A1"),
            ("Dep resolved", "DEP_RESOLVED"),
            ("Xray go", "XRAY_GO"),
        ],
    )
    def test_a_label_is_cut_to_an_upper_case_event_name(self, label: str, event: str) -> None:
        text = f"stateDiagram-v2\n  [*] --> a\n  a --> b : {label}\n"

        assert list(draft_machine("m", parse(text))["events"]) == [event]

    def test_a_label_that_does_not_start_with_a_letter_is_refused(self) -> None:
        with pytest.raises(MachineDefinitionError) as refused:
            draft_machine("m", parse("stateDiagram-v2\n  [*] --> a\n  a --> b : 42\n"))

        assert str(refused.value) == "cannot name an event from the label '42': it must start with a letter"


class TestDump:
    def test_a_header_names_the_source_and_keys_keep_their_order(self) -> None:
        draft = draft_machine("m", parse("stateDiagram-v2\n  [*] --> a\n  a --> b : Go\n"))

        assert mermaid_import.dump(draft, "m.mmd") == (
            "# Draft imported from m.mmd: add guards and actions by hand.\n"
            "name: m\n"
            "states:\n"
            "  a:\n"
            "    initial: true\n"
            "  b: {}\n"
            "events:\n"
            "  GO:\n"
            "  - from: a\n"
            "    to: b\n"
        )

    def test_no_source_means_no_header(self) -> None:
        assert mermaid_import.dump({"name": "m"}) == "name: m\n"


class TestMain:
    def test_writes_the_draft_beside_the_machines(self, tmp_path: Path) -> None:
        source = tmp_path / "flow.mmd"
        source.write_text(SAMPLE)
        out = tmp_path / "flow.yaml"

        mermaid_import.main([str(source), "--out", str(out)])

        validate(yaml.safe_load(out.read_text()))
        assert yaml.safe_load(out.read_text())["name"] == "flow"

    def test_help_describes_the_command(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("COLUMNS", "200")

        with pytest.raises(SystemExit) as helped:
            mermaid_import.main(["--help"])

        assert helped.value.code == 0
        assert (
            "Draft a StarPulse machine definition from a stateDiagram-v2 file." in capsys.readouterr().out.splitlines()
        )

    def test_without_out_it_writes_under_the_machines_directory_and_says_where(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".starpulse" / "machines").mkdir(parents=True)
        (tmp_path / "flow.mmd").write_text(SAMPLE)
        monkeypatch.chdir(tmp_path)

        mermaid_import.main(["flow.mmd"])

        written = tmp_path / ".starpulse" / "machines" / "flow.yaml"
        assert written.read_text().startswith("# Draft imported from flow.mmd: add guards and actions by hand.\n")
        assert capsys.readouterr().out == f"Wrote {Path('.starpulse/machines/flow.yaml')}\n"

    def test_never_overwrites_an_authored_definition(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = tmp_path / "flow.mmd"
        source.write_text(SAMPLE)
        out = tmp_path / "flow.yaml"
        out.write_text("authored: true\n")

        with pytest.raises(SystemExit) as refused:
            mermaid_import.main([str(source), "--out", str(out)])

        assert refused.value.code == 2
        assert str(source) in capsys.readouterr().err
        assert out.read_text() == "authored: true\n"

    def test_a_diagram_it_cannot_draft_writes_nothing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = tmp_path / "flow.mmd"
        source.write_text("flowchart TD\n")
        out = tmp_path / "flow.yaml"

        with pytest.raises(SystemExit):
            mermaid_import.main([str(source), "--out", str(out)])

        assert "not a stateDiagram-v2 file" in capsys.readouterr().err
        assert not out.exists()

    def test_a_file_name_the_schema_refuses_is_reported_not_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = tmp_path / "1flow.mmd"
        source.write_text(SAMPLE)
        out = tmp_path / "out.yaml"

        with pytest.raises(SystemExit):
            mermaid_import.main([str(source), "--out", str(out)])

        assert "name" in capsys.readouterr().err
        assert not out.exists()
