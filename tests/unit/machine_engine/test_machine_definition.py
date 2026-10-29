"""A YAML machine compiles to the same machine its Python class declares, and the schema keeps config inert."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from starpulse.machine_engine.adapters import machine_loader
from starpulse.machine_engine.adapters.machine_loader import load_machine, validate
from starpulse.machine_engine.model.machine_definition import (
    Cue,
    MachineDefinitionError,
    Registry,
    Writer,
    refuse_unlisted,
    role_of,
    writers_of,
)
from starpulse.machine_engine.model.snapshot import describe
from statemachine import StateChart

MACHINES = Path(__file__).parent.parent.parent / "fixtures" / "machines"

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
        schema = Path(machine_loader.__file__).parents[2] / "schemas" / "machine.schema.json"

        assert json.loads(schema.read_text()) == machine_loader.SCHEMA


def _review(waits: dict[str, Any]) -> dict[str, Any]:
    """A machine whose `review` state declares `waits` and leaves on `MERGED`."""
    return {
        "name": "sample",
        "states": {"review": {"initial": True, "waits": waits}, "done": {"final": True}},
        "events": {"MERGED": [{"from": "review", "to": "done"}]},
    }


class TestWaits:
    def test_a_state_declaring_waits_reads_them_back_from_the_loaded_machine(self, tmp_path: Path) -> None:
        compiled = load_machine(_written(tmp_path, _review({"pr_terminal": "MERGED"})))

        assert compiled.waits == {"review": {"pr_terminal": "MERGED"}}

    def test_a_state_waiting_on_a_ready_pull_request_reads_it_back_from_the_loaded_machine(
        self, tmp_path: Path
    ) -> None:
        compiled = load_machine(_written(tmp_path, _review({"pr_ready": "MERGED"})))

        assert compiled.waits == {"review": {"pr_ready": "MERGED"}}

    def test_a_review_state_routing_a_merge_on_the_verify_plan_reads_both_facts_back(self, tmp_path: Path) -> None:
        machine = _review({"pr_merged_planned": "MERGED_VERIFY", "pr_merged": "MERGED"})
        machine["states"]["verifying"] = {"final": True}
        machine["events"]["MERGED_VERIFY"] = [{"from": "review", "to": "verifying"}]

        compiled = load_machine(_written(tmp_path, machine))

        assert compiled.waits == {"review": {"pr_merged_planned": "MERGED_VERIFY", "pr_merged": "MERGED"}}

    def test_a_machine_whose_states_wait_on_nothing_has_no_waits(self, tmp_path: Path) -> None:
        assert load_machine(_written(tmp_path, _doc())).waits == {}

    def test_an_unknown_fact_kind_is_refused_naming_the_state_and_event(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _review({"moon_phase": "MERGED"}))

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        message = str(raised.value)
        assert "review" in message and "MERGED" in message and "moon_phase" in message

    def test_an_event_that_does_not_leave_the_state_is_refused_naming_the_state_and_event(self, tmp_path: Path) -> None:
        document = _review({"deps_done": "DEPS_DONE"})
        document["events"]["DEPS_DONE"] = [{"from": "done", "to": "done"}]
        path = _written(tmp_path, document)

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        message = str(raised.value)
        assert "review" in message and "DEPS_DONE" in message

    def test_an_event_the_machine_lacks_is_refused_naming_the_state_and_event(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _review({"criteria_met": "CRITERIA_MET"}))

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        message = str(raised.value)
        assert "review" in message and "CRITERIA_MET" in message


_CUE = {"event": "GO", "dag": "dagu/apply-on-merge", "on": "push to main", "resolves": "forced"}


class TestCues:
    def test_a_cues_block_loads_with_its_event_dag_on_and_resolves(self, tmp_path: Path) -> None:
        other = {"event": "GO", "dag": "dagu/healthcheck", "on": "push to main", "resolves": "next"}

        compiled = load_machine(_written(tmp_path, _doc(cues=[_CUE, other])))

        assert compiled.cues == (
            Cue("GO", "dagu/apply-on-merge", "push to main", "forced"),
            Cue("GO", "dagu/healthcheck", "push to main", "next"),
        )

    def test_a_cue_may_declare_the_seconds_its_run_has_to_start_and_otherwise_gets_five_minutes(
        self, tmp_path: Path
    ) -> None:
        timed = {**_CUE, "dag": "dagu/healthcheck", "grace": 120}

        compiled = load_machine(_written(tmp_path, _doc(cues=[_CUE, timed])))

        assert [cue.grace for cue in compiled.cues] == [300, 120]

    def test_a_grace_that_is_not_a_positive_whole_number_is_refused(self, tmp_path: Path) -> None:
        for grace in (0, -5, 1.5, "soon"):
            with pytest.raises(MachineDefinitionError):
                load_machine(_written(tmp_path, _doc(cues=[{**_CUE, "grace": grace}])))

    def test_a_bare_on_key_in_the_yaml_is_the_cues_on_not_a_boolean(self, tmp_path: Path) -> None:
        path = tmp_path / "sample.yaml"
        path.write_text(
            "name: sample\nstates: {a: {initial: true}, b: {final: true}}\nevents: {GO: [{from: a, to: b}]}\n"
            "cues:\n  - event: GO\n    dag: dagu/apply-on-merge\n    on: push to main\n    resolves: forced\n"
        )

        assert load_machine(path).cues == (Cue("GO", "dagu/apply-on-merge", "push to main", "forced"),)

    def test_a_machine_without_a_cues_block_has_no_cues(self, tmp_path: Path) -> None:
        assert load_machine(_written(tmp_path, _doc())).cues == ()

    @pytest.mark.parametrize(
        "cues",
        [
            [{k: v for k, v in _CUE.items() if k != "dag"}],
            [{k: v for k, v in _CUE.items() if k != "event"}],
            [{k: v for k, v in _CUE.items() if k != "on"}],
            [{k: v for k, v in _CUE.items() if k != "resolves"}],
            [{**_CUE, "resolves": "never"}],
            [{**_CUE, "dag": ""}],
            [{**_CUE, "run": "rm -rf /"}],
            {"GO": _CUE},
            [],
        ],
    )
    def test_a_cue_missing_a_field_or_resolving_any_other_way_is_rejected(self, cues: object) -> None:
        with pytest.raises(MachineDefinitionError):
            validate(_doc(cues=cues))

    def test_a_cue_on_an_event_the_machine_lacks_is_refused_naming_the_event(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc(cues=[{**_CUE, "event": "STOP"}]))

        with pytest.raises(MachineDefinitionError, match=r"cues name events the machine lacks: \['STOP'\]"):
            load_machine(path)


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

    def test_a_when_guard_reads_as_the_fields_it_matches(self, tmp_path: Path) -> None:
        # A diagram labels a guard by its callable's name; every matcher would otherwise read `matches`.
        guards = (
            {"if": {"when": {"ready": {"equals": True}}}},
            {"unless": {"when": {"held": {"equals": True}}}},
            {"if": {"when": {"branch": {"in": ["main", "dev"]}, "kind": {"equals": "push"}}}},
            {"if": {"when": {"sha": {"exists": True}, "tag": {"exists": False}}}},
        )
        path = _written(tmp_path, _doc(*({"from": "a", "to": "b", **guard} for guard in guards)))
        transitions = load_machine(path).machine.states_map["a"].transitions

        assert [str(guard) for transition in transitions for guard in transition.cond] == [
            "ready",
            "!held",
            "branch in [main, dev] and kind == push",
            "sha exists and tag missing",
        ]

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

    @pytest.mark.parametrize("trigger", ["the docs step's task comment", "a reply asking for approval", "after review"])
    def test_an_agent_trigger_in_prose_on_a_final_event_is_refused_by_event(self, tmp_path: Path, trigger: str) -> None:
        path = _written(tmp_path, _doc(writers={"GO": [{"actor": "agent", "trigger": trigger}]}))

        with pytest.raises(MachineDefinitionError, match="GO"):
            load_machine(path)

    @pytest.mark.parametrize("trigger", ["make lint-docs", "./.venv/bin/backlog-task park", "Skill", "gh pr ready"])
    def test_an_agent_trigger_naming_a_command_or_tool_on_a_final_event_is_accepted(
        self, tmp_path: Path, trigger: str
    ) -> None:
        load_machine(_written(tmp_path, _doc(writers={"GO": [{"actor": "agent", "trigger": trigger}]})))

    def test_prose_is_accepted_off_a_final_event_and_from_a_person(self, tmp_path: Path) -> None:
        states = {"a": {"initial": True}, "b": {}, "c": {"final": True}}
        document = _doc({"from": "a", "to": "b"}, states=states)
        document["events"]["DONE"] = [{"from": "b", "to": "c"}]
        document["writers"] = {
            "GO": [{"actor": "agent", "trigger": "the first reply"}],
            "DONE": [{"actor": "operator", "trigger": "merge the pull request"}],
        }

        load_machine(_written(tmp_path, document))

    def test_a_workflow_no_adapter_lists_is_refused_by_name(self) -> None:
        writers = {"GO": (Writer("agent", "bin/go"), Writer("dagu/ghost", "bin/ghost.py"))}

        with pytest.raises(MachineDefinitionError, match="dagu/ghost"):
            refuse_unlisted("sample", writers, {"dagu/nightly"})

    def test_listed_workflows_and_bare_actors_are_accepted(self) -> None:
        writers = {"GO": (Writer("agent", "bin/go"), Writer("dagu/nightly", "bin/nightly.py"))}

        refuse_unlisted("sample", writers, {"dagu/nightly"})


class TestSubflowsAreRefused:
    def test_the_old_key_is_refused_naming_the_file_and_the_new_key(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _doc(subflows=[{"state": "a", "flow": "child.yaml", "exits": {}}]))

        with pytest.raises(MachineDefinitionError) as raised:
            load_machine(path)

        assert str(raised.value).startswith(f"{path}: `subflows:` is now `submachines:`")


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


class TestCitations:
    CITE = {"skill": "completing-tasks", "quote": "Only exit 3 is a blocker"}

    def test_a_transition_may_cite_the_skill_sentence_that_authorizes_it(self) -> None:
        validate(_doc({"from": "a", "to": "b", "cite": self.CITE}))

    @pytest.mark.parametrize("cite", [{"skill": "completing-tasks"}, {"quote": "q"}, {**CITE, "page": 3}, "skill"])
    def test_a_citation_without_a_skill_and_quote_or_with_more_is_refused(self, cite: Any) -> None:
        with pytest.raises(MachineDefinitionError, match="cite"):
            validate(_doc({"from": "a", "to": "b", "cite": cite}))

    def test_a_citation_is_kept_per_source_event_and_target_and_drawn_on_the_transition(self, tmp_path: Path) -> None:
        document = _doc(
            {"from": ["a", "c"], "to": "b", "cite": self.CITE},
            {"from": "a", "to": "c"},
            states={"a": {"initial": True}, "b": {"final": True}, "c": {}},
        )
        machine = load_machine(_written(tmp_path, document)).machine

        assert machine.citations == {("a", "GO", "b"): self.CITE, ("c", "GO", "b"): self.CITE}
        assert sorted((t for t in describe(machine)["transitions"] if "cite" in t), key=lambda t: t["source"]) == [
            {"source": "a", "target": "b", "event": "GO", "cite": self.CITE},
            {"source": "c", "target": "b", "event": "GO", "cite": self.CITE},
        ]

    def test_an_uncited_transition_draws_no_cite(self, tmp_path: Path) -> None:
        machine = load_machine(_written(tmp_path, _doc())).machine

        assert all("cite" not in t for t in describe(machine)["transitions"])


def _roled(role: object) -> dict[str, Any]:
    """A machine whose `parked` state declares `role`, between an initial and a final state."""
    return {
        "name": "sample",
        "states": {"open": {"initial": True}, "parked": {"role": role}, "shut": {"final": True}},
        "events": {"PARK": [{"from": "open", "to": "parked"}], "SHUT": [{"from": "parked", "to": "shut"}]},
    }


class TestRoles:
    @pytest.mark.parametrize("role", ["resting", "waiting_on_fact", "waiting_on_person"])
    def test_a_state_declares_its_role_and_a_renamed_state_resolves_the_same(self, tmp_path: Path, role: str) -> None:
        compiled = load_machine(_written(tmp_path, _roled(role)))

        assert role_of(compiled, "parked") == role

    def test_the_initial_and_final_flags_resolve_as_the_initial_and_final_roles(self, tmp_path: Path) -> None:
        compiled = load_machine(_written(tmp_path, _roled("resting")))

        assert (role_of(compiled, "open"), role_of(compiled, "shut")) == ("initial", "final")

    def test_a_state_declaring_no_role_resolves_to_none(self, tmp_path: Path) -> None:
        document = _roled("resting")
        del document["states"]["parked"]["role"]

        assert role_of(load_machine(_written(tmp_path, document)), "parked") is None

    @pytest.mark.parametrize("role", ["initial", "done", 3])
    def test_an_unknown_role_is_rejected_by_the_schema(self, role: object) -> None:
        with pytest.raises(MachineDefinitionError):
            validate(_roled(role))

    def test_resolving_a_state_the_machine_lacks_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            role_of(load_machine(_written(tmp_path, _roled("resting"))), "nowhere")


class TestStateLabel:
    def test_a_state_label_is_exposed_and_defaults_to_the_state_id(self, tmp_path: Path) -> None:
        document = _roled("resting")
        document["states"]["parked"]["label"] = "Needs attention"

        compiled = load_machine(_written(tmp_path, document))

        assert compiled.labels == {"open": "open", "parked": "Needs attention", "shut": "shut"}

    @pytest.mark.parametrize("label", [3, None, ["x"], ""])
    def test_a_label_that_is_not_a_non_empty_string_is_rejected_by_the_schema(self, label: object) -> None:
        document = _roled("resting")
        document["states"]["parked"]["label"] = label

        with pytest.raises(MachineDefinitionError):
            validate(document)


def test_the_machine_schema_lives_in_the_schemas_directory() -> None:
    schema_path = Path(machine_loader.__file__).parents[2] / "schemas" / "machine.schema.json"
    assert schema_path.is_file()
    document = json.loads(schema_path.read_text())
    assert document["title"] == "StarPulse machine definition"
