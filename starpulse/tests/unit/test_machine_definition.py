"""A YAML machine compiles to the same machine its Python class declares, and the schema keeps config inert."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from statemachine import StateChart

from starpulse import machine_definition
from starpulse.machine_definition import (
    MachineDefinitionError,
    Registry,
    Writer,
    load_machine,
    refuse_unlisted,
    validate,
    writers_of,
)

MACHINES = Path(__file__).parent.parent / "fixtures" / "machines"

PULL_REQUEST_REGISTRY = Registry(
    guards={"draft": lambda model: model.draft},
    actions={"mark_ready": lambda model: setattr(model, "draft", False)},
)


class _Model:
    """A pull request's one fact the fixture's guard reads and its action writes."""

    def __init__(self) -> None:
        self.draft = True


def _twin() -> Callable[[], StateChart]:
    machine = load_machine(MACHINES / "pull_request.yaml", PULL_REQUEST_REGISTRY).machine
    return lambda: machine(model=_Model())


def _doc(*transitions: dict[str, Any], states: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "name": "sample",
        "states": states or {"a": {"initial": True}, "b": {"final": True}},
        "events": {"GO": list(transitions) or [{"from": "a", "to": "b"}]},
        **extra,
    }


def _written(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "sample.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


class TestTheCompiledPullRequest:
    def test_a_draft_is_not_merged_and_a_readied_pr_is(self) -> None:
        machine = _twin()()
        for event in ("PR_OPENED", "CI_GREEN", "MERGED"):
            machine.send(event)
        assert machine.model.draft is True
        assert {s.id for s in machine.configuration} == {"ci_green"}

        for event in ("READIED", "MERGED"):
            machine.send(event)

        assert machine.model.draft is False
        assert machine.is_terminated


class TestTheSchema:
    @pytest.mark.parametrize(
        "guard",
        [
            {"when": {"kind": {"equals": "push"}}},
            {"when": {"branch": {"in": ["main", "release"]}}},
            {"when": {"sha": {"exists": True}}},
            {"when": {"kind": {"equals": "push"}, "sha": {"exists": False}}},
            "draft",
        ],
    )
    @pytest.mark.parametrize("key", ["if", "unless"])
    def test_a_field_match_or_a_named_guard_is_accepted(self, key: str, guard: object) -> None:
        validate(_doc({"from": "a", "to": "b", key: guard}))

    @pytest.mark.parametrize(
        "guard",
        [
            "event.kind == 'push'",
            "draft and ready",
            "__import__('os').system('id')",
            {"expr": "event.kind == 'push'"},
            {"python": "return True"},
            {"when": {"kind": {"equals": "push"}}, "code": "return True"},
            {"when": {"kind": {"matches": ".*"}}},
            {"when": {"kind": {"equals": "push", "exists": True}}},
            {"when": {"kind": "push"}},
            {"when": {}},
            {"when": {"event": {"equals": "push"}}},
            {"when": {"kind": {"in": []}}},
        ],
    )
    def test_an_expression_inline_code_or_an_unknown_key_in_a_guard_is_rejected(self, guard: object) -> None:
        with pytest.raises(MachineDefinitionError):
            validate(_doc({"from": "a", "to": "b", "if": guard}))

    @pytest.mark.parametrize(
        "document",
        [
            {**_doc(), "extra": 1},
            _doc({"from": "a", "to": "b", "run": "rm -rf /"}),
            _doc(states={"a": {"initial": True, "enter": "code"}}),
            _doc({"from": "a", "to": "b", "action": "mark ready"}),
            {k: v for k, v in _doc().items() if k != "events"},
        ],
    )
    def test_an_unknown_key_or_a_missing_section_is_rejected(self, document: dict[str, Any]) -> None:
        with pytest.raises(MachineDefinitionError):
            validate(document)

    @pytest.mark.parametrize(
        "writers",
        [
            {"GO": [{"actor": "agent", "trigger": "bin/backlog_task.py review"}]},
            {"GO": [{"actor": "dagu/main-follow", "trigger": "bin/board_reconcile_merged.py"}]},
            {"GO": [{"actor": "prod/nested/wf", "trigger": "t"}, {"actor": "operator", "trigger": "u"}]},
        ],
    )
    def test_a_writers_list_per_event_naming_an_actor_or_a_workflow_is_accepted(self, writers: object) -> None:
        validate(_doc(writers=writers))

    @pytest.mark.parametrize(
        "writers",
        [
            [{"actor": "agent", "trigger": "t"}],
            {"GO": {"actor": "agent", "trigger": "t"}},
            {"GO": []},
            {"GO": ["agent"]},
            {"GO": [{"actor": "agent"}]},
            {"GO": [{"trigger": "t"}]},
            {"GO": [{"actor": "agent", "trigger": ""}]},
            {"GO": [{"actor": "agent", "trigger": "t", "run": "rm -rf /"}]},
            {"GO": [{"actor": "dagu/", "trigger": "t"}]},
            {"GO": [{"actor": "/wf", "trigger": "t"}]},
            {"GO": [{"actor": "two words", "trigger": "t"}]},
            {"GO": [{"actor": "", "trigger": "t"}]},
            {"not an event": [{"actor": "agent", "trigger": "t"}]},
        ],
    )
    def test_any_other_shape_of_writers_is_rejected(self, writers: object) -> None:
        with pytest.raises(MachineDefinitionError):
            validate(_doc(writers=writers))

    def test_the_published_schema_is_the_one_that_validates(self) -> None:
        schema = Path(machine_definition.__file__).with_name("machine.schema.json")

        assert json.loads(schema.read_text()) == machine_definition.SCHEMA


class TestCompiling:
    def test_a_when_guard_matches_the_triggering_event_fields(self, tmp_path: Path) -> None:
        document = _doc({"from": "a", "to": "b", "if": {"when": {"branch": {"in": ["main"]}, "sha": {"exists": True}}}})
        machine = load_machine(_written(tmp_path, document)).machine

        refused = machine()
        refused.send("GO", branch="main")
        refused.send("GO", branch="dev", sha="abc")
        accepted = machine()
        accepted.send("GO", branch="main", sha="abc")

        assert not refused.is_terminated
        assert accepted.is_terminated

    def test_an_equals_guard_and_an_unless_guard_read_the_event_fields(self, tmp_path: Path) -> None:
        document = _doc({"from": "a", "to": "b", "unless": {"when": {"kind": {"equals": "draft"}}}})
        machine = load_machine(_written(tmp_path, document)).machine

        held = machine()
        held.send("GO", kind="draft")
        released = machine()
        released.send("GO", kind="push")

        assert not held.is_terminated
        assert released.is_terminated

    def test_a_named_guard_reads_as_its_registered_name_and_still_takes_injected_arguments(
        self, tmp_path: Path
    ) -> None:
        # A diagram labels a guard by its callable's name; a registered lambda would read `<lambda>`.
        path = _written(tmp_path, _doc({"from": "a", "to": "b", "if": "ready", "unless": "held"}))
        registry = Registry(guards={"ready": lambda kind: kind == "push", "held": lambda: False})
        machine = load_machine(path, registry).machine

        refused, accepted = machine(), machine()
        refused.send("GO", kind="draft")
        accepted.send("GO", kind="push")

        (transition,) = machine.states_map["a"].transitions
        assert [str(guard) for guard in transition.cond] == ["ready", "!held"]
        assert (refused.is_terminated, accepted.is_terminated) == (False, True)

    def test_a_named_guard_the_adapter_did_not_register_is_refused(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc({"from": "a", "to": "b", "if": "unregistered"}))

        with pytest.raises(MachineDefinitionError, match="unregistered"):
            load_machine(path)

    def test_a_named_action_the_adapter_did_not_register_is_refused(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc({"from": "a", "to": "b", "action": "unregistered"}))

        with pytest.raises(MachineDefinitionError, match="unregistered"):
            load_machine(path)

    def test_a_transition_naming_an_undeclared_state_is_refused(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc({"from": "a", "to": "nowhere"}))

        with pytest.raises(MachineDefinitionError, match="nowhere"):
            load_machine(path)

    def test_a_machine_needs_exactly_one_initial_state(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc(states={"a": {}, "b": {"final": True}}))

        with pytest.raises(MachineDefinitionError, match="initial"):
            load_machine(path)

    def test_bindings_map_adapter_events_to_declared_machine_events(self, tmp_path: Path) -> None:
        compiled = load_machine(MACHINES / "pull_request.yaml", PULL_REQUEST_REGISTRY)
        refused = _written(tmp_path, _doc(bindings={"adapter.go": "MISSING"}))

        assert compiled.bindings == {
            "github.pull_request.created": "PR_OPENED",
            "github.pull_request.merged": "MERGED",
        }
        with pytest.raises(MachineDefinitionError, match="MISSING"):
            load_machine(refused)


class TestWriters:
    WRITERS = {
        "GO": [
            {"actor": "agent", "trigger": "bin/go"},
            {"actor": "dagu/nightly", "trigger": "bin/nightly.py"},
        ]
    }

    def test_the_compiler_carries_each_events_writers_on_the_result_and_the_class(self, tmp_path: Path) -> None:
        compiled = load_machine(_written(tmp_path, _doc(writers=self.WRITERS)))

        expected = {"GO": (Writer("agent", "bin/go"), Writer("dagu/nightly", "bin/nightly.py"))}
        assert compiled.writers == expected
        assert writers_of(compiled.machine) == expected

    def test_a_machine_that_declares_none_carries_none(self, tmp_path: Path) -> None:
        assert load_machine(_written(tmp_path, _doc())).writers == {}

    def test_writers_for_an_event_the_machine_lacks_are_refused_by_event(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc(writers={"NOPE": [{"actor": "agent", "trigger": "t"}]}))

        with pytest.raises(MachineDefinitionError, match="NOPE"):
            load_machine(path)

    def test_a_workflow_no_adapter_lists_is_refused_by_name(self) -> None:
        writers = {"GO": (Writer("agent", "bin/go"), Writer("dagu/ghost", "bin/ghost.py"))}

        with pytest.raises(MachineDefinitionError, match="dagu/ghost"):
            refuse_unlisted("sample", writers, {"dagu/nightly"})

    def test_listed_workflows_and_bare_actors_are_accepted(self) -> None:
        writers = {"GO": (Writer("agent", "bin/go"), Writer("dagu/nightly", "bin/nightly.py"))}

        refuse_unlisted("sample", writers, {"dagu/nightly"})


class TestSubflows:
    def test_a_state_opens_a_child_machine_file_as_a_nested_machine(self) -> None:
        machine = load_machine(MACHINES / "deploy.yaml").machine()

        machine.send("STARTED")
        assert {s.id for s in machine.configuration} == {"rollout", "rollout_canary"}

        machine.send("PROMOTED")
        assert {s.id for s in machine.configuration} == {"rollout", "rollout_fleet"}

        machine.send("FINISHED")
        assert machine.is_terminated

    def test_a_second_nesting_level_is_rejected(self) -> None:
        with pytest.raises(MachineDefinitionError, match="one level"):
            load_machine(MACHINES / "nested.yaml")

    def test_a_missing_child_file_is_refused(self, tmp_path: Path) -> None:
        document = _doc(states={"a": {"initial": True, "flow": "absent.yaml"}, "b": {"final": True}})

        with pytest.raises(MachineDefinitionError, match="absent.yaml"):
            load_machine(_written(tmp_path, document))


class TestErrorsNameTheirSource:
    def test_a_schema_error_names_the_file_and_the_offending_key(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc({"from": "a", "to": "b", "if": "not valid"}))

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        assert str(raised.value).startswith(f"{path}: events/GO/0/if: ")

    def test_a_document_level_schema_error_is_located_at_the_root(self) -> None:
        with pytest.raises(MachineDefinitionError) as raised:
            validate({})

        assert str(raised.value).startswith("<root>: ")

    def test_a_malformed_yaml_file_is_named(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("name: [unclosed")

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        assert str(raised.value).startswith(f"{path}: ")

    def test_a_definition_the_state_machine_library_refuses_is_named(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc({"from": "a", "to": "a"}))

        with pytest.raises(MachineDefinitionError, match="unreachable") as raised:
            load_machine(path)

        assert str(raised.value).startswith(f"{path}: ")

    @pytest.mark.parametrize("key", ["if", "action"])
    def test_an_unregistered_name_is_named_with_its_file(self, tmp_path: Path, key: str) -> None:
        path = _written(tmp_path, _doc({"from": "a", "to": "b", key: "unregistered"}))

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        assert str(raised.value) == f"{path}: 'unregistered' is not registered by the adapter"

    def test_the_compiled_machine_carries_its_declared_name(self) -> None:
        assert load_machine(MACHINES / "deploy.yaml").name == "deploy"

    def test_a_class_style_name_names_the_compiled_class(self, tmp_path: Path) -> None:
        # A consumer that records `type(machine).__name__` keeps reading the name a Python class had.
        compiled = load_machine(_written(tmp_path, {**_doc(), "name": "InProgress"}))

        assert compiled.machine.__name__ == "InProgress"


class TestGuardsAndStatesOnTheEdges:
    def test_an_equals_or_in_match_on_an_absent_field_does_not_hold(self, tmp_path: Path) -> None:
        for match in ({"equals": "main"}, {"in": ["main"]}):
            machine = load_machine(
                _written(tmp_path, _doc({"from": "a", "to": "b", "if": {"when": {"branch": match}}}))
            )
            absent = machine.machine()

            absent.send("GO")

            assert not absent.is_terminated, match

    def test_the_declared_initial_state_starts_the_machine_not_one_the_library_would_infer(
        self, tmp_path: Path
    ) -> None:
        document = _doc(
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
            states={"a": {}, "b": {"initial": True}},
        )

        machine = load_machine(_written(tmp_path, document)).machine()

        assert [state.id for state in machine.configuration] == ["b"]


class TestSubflowFiles:
    def _parent(self, tmp_path: Path, child: dict[str, Any], **parent: Any) -> Path:
        (tmp_path / "child.yaml").write_text(yaml.safe_dump(child))
        document = {
            "name": "parent",
            "states": {"top": {"initial": True, "flow": "child.yaml"}},
            "events": {"STOP": [{"from": "top", "to": "top"}]},
            **parent,
        }
        path = tmp_path / "parent.yaml"
        path.write_text(yaml.safe_dump(document))
        return path

    def _child(self, **extra: Any) -> dict[str, Any]:
        return {
            "name": "child",
            "states": {"one": {"initial": True}, "two": {}},
            "events": {"NEXT": [{"from": "one", "to": "two"}]},
            **extra,
        }

    def test_child_bindings_join_the_parents(self, tmp_path: Path) -> None:
        path = self._parent(tmp_path, self._child(bindings={"adapter.next": "NEXT"}), bindings={"adapter.stop": "STOP"})

        assert load_machine(path).bindings == {"adapter.stop": "STOP", "adapter.next": "NEXT"}

    def test_a_child_binding_an_adapter_event_the_parent_binds_is_refused(self, tmp_path: Path) -> None:
        path = self._parent(tmp_path, self._child(bindings={"adapter.go": "NEXT"}), bindings={"adapter.go": "STOP"})

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        assert str(raised.value) == f"{tmp_path / 'child.yaml'}: bindings already bound by {path}: ['adapter.go']"

    def test_a_child_uses_the_adapters_registered_guards(self, tmp_path: Path) -> None:
        child = self._child(events={"NEXT": [{"from": "one", "to": "two", "if": "ready"}]})
        path = self._parent(tmp_path, child)

        machine = load_machine(path, Registry(guards={"ready": lambda: True})).machine()
        machine.send("NEXT")

        assert {state.id for state in machine.configuration} == {"top", "top_two"}

    def test_an_error_in_a_child_names_the_child_file(self, tmp_path: Path) -> None:
        child = self._child(events={"NEXT": [{"from": "one", "to": "two", "if": "unregistered"}]})
        path = self._parent(tmp_path, child)

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        assert str(raised.value).startswith(f"{tmp_path / 'child.yaml'}: ")
