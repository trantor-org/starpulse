"""The static shape the page draws: a machine's states and transitions, and the declared workflow relationships."""

from pathlib import Path

import pytest
import yaml
from starpulse.contracts.api.dto.machine import Cite, MachineState, Transition
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model import snapshot
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError
from starpulse.machine_engine.model.snapshot import describe
from statemachine import State, StateChart

from tests.machines import FIXTURES


class _Tiny(StateChart):
    a = State("A", initial=True)
    b = State("B", final=True)

    GO = a.to(b)
    STAY = a.to.itself()


class TestDescribe:
    def test_a_machine_is_its_states_and_every_transition_including_self_loops(self) -> None:
        assert describe(_Tiny) == {
            "states": [
                {"id": "a", "name": "A", "initial": True, "final": False, "role": None},
                {"id": "b", "name": "B", "initial": False, "final": True, "role": None},
            ],
            "transitions": [
                {"source": "a", "target": "b", "event": "GO"},
                {"source": "a", "target": "a", "event": "STAY"},
            ],
        }

    def test_each_state_is_served_with_the_type_its_yaml_declares(self) -> None:
        states = describe(load_machine(FIXTURES / "renamed-board.yaml").machine)["states"]

        assert {s["id"]: s["role"] for s in states} == {
            "inbox": "initial",
            "todo": "waiting_on_fact",
            "parked": "waiting_on_fact",
            "doing": "resting",
            "checking": "waiting_on_fact",
            "on_me": "waiting_on_person",
            "shipped": "resting",
            "gone": "final",
        }

    def test_a_state_the_machine_rests_in_is_served_as_the_final_type(self) -> None:
        compiled = load_machine(FIXTURES / "renamed-board.yaml")

        states = describe(compiled.machine, compiled.drawing["rests"])["states"]

        assert {s["id"]: s["role"] for s in states}["shipped"] == "final"

    def test_a_served_state_validates_as_the_api_state_with_its_role(self) -> None:
        state = describe(load_machine(FIXTURES / "renamed-board.yaml").machine)["states"][1]

        assert MachineState.model_validate(state).model_dump()["role"] == "waiting_on_fact"


class TestDeclared:
    def test_the_board_adapters_cues_are_served_as_it_gives_them(self) -> None:
        cues = [{"dag": "q/nightly", "event": "MERGED", "state": "done", "on": "each merge"}]

        assert snapshot.declared(cues=cues)["cues"] == cues

    def test_each_domain_lists_the_workflows_the_config_gives_it_with_the_run_safe_flag(self) -> None:
        domains = snapshot.declared(
            {"Ops": ("prod/nightly", "prod/backup"), "Data": ("staging/nightly",)}, {"prod/nightly", "staging/nightly"}
        )["domains"]

        assert domains == [
            {
                "name": "Ops",
                "dags": [{"name": "prod/nightly", "runSafe": True}, {"name": "prod/backup", "runSafe": False}],
                "processes": [],
            },
            {"name": "Data", "dags": [{"name": "staging/nightly", "runSafe": True}], "processes": []},
        ]

    def test_without_config_domains_none_is_drawn_and_none_is_run_safe(self) -> None:
        assert snapshot.declared()["domains"] == []

    def test_only_cues_and_domains_are_served(self) -> None:
        assert set(snapshot.declared()) == {"cues", "domains"}

    def test_it_carries_each_domains_processes(self) -> None:
        body = snapshot.declared(
            domains={"Ops": ("dagu/nightly", "dagu/backup")},
            processes={"Ops": (("Nightly", ("dagu/nightly",)), ("Backup", ("dagu/backup",)))},
            run_safe=("dagu/nightly",),
        )
        assert body["domains"] == [
            {
                "name": "Ops",
                "dags": [{"name": "dagu/nightly", "runSafe": True}, {"name": "dagu/backup", "runSafe": False}],
                "processes": [
                    {"name": "Nightly", "dags": [{"name": "dagu/nightly", "runSafe": True}]},
                    {"name": "Backup", "dags": [{"name": "dagu/backup", "runSafe": False}]},
                ],
            }
        ]


class TestQualifier:
    def test_a_workflow_one_instance_lists_is_named_by_that_instance(self) -> None:
        qualify = snapshot.qualifier({"Ops": ("prod/nightly",), "Data": ("staging/etl",)})

        assert (qualify("nightly"), qualify("etl")) == ("prod/nightly", "staging/etl")

    def test_a_workflow_two_instances_list_stays_bare_because_it_names_neither(self) -> None:
        assert snapshot.qualifier({"Ops": ("prod/nightly", "staging/nightly")})("nightly") == "nightly"

    def test_a_name_no_instance_lists_stays_as_it_is(self) -> None:
        qualify = snapshot.qualifier({"Ops": ("prod/nightly",)})

        assert (qualify("operator"), qualify("agent")) == ("operator", "agent")

    def test_a_workflow_name_with_a_slash_is_qualified_whole(self) -> None:
        assert snapshot.qualifier({"Ops": ("prod/nested/wf",)})("nested/wf") == "prod/nested/wf"

    def test_an_already_qualified_name_stays_as_it_is(self) -> None:
        assert snapshot.qualifier({"Ops": ("prod/nightly",)})("prod/nightly") == "prod/nightly"


class TestStateNames:
    def test_every_word_of_a_state_name_is_capitalised(self) -> None:
        class Lanes(StateChart):
            ready = State("ready", initial=True)
            in_progress = State("in progress", final=True)

            START = ready.to(in_progress)

        assert [s["name"] for s in describe(Lanes)["states"]] == ["Ready", "In Progress"]

    def test_titling_changes_only_first_letters(self) -> None:
        assert snapshot._titled("PR opened  twice") == "PR Opened  Twice"


class TestSource:
    """A machine a third party moves says so: the snapshot carries its `source`, and a local machine has none."""

    @staticmethod
    def _drawn(tmp_path: Path, **extra: object) -> dict:
        document = {
            "name": "sample",
            "states": {"a": {"initial": True}, "b": {"final": True}},
            "events": {"GO": [{"from": "a", "to": "b"}]},
        }
        path = tmp_path / "sample.yaml"
        path.write_text(yaml.safe_dump(document | extra))
        return describe(load_machine(path).machine)

    def test_a_machine_that_declares_a_source_carries_it_to_the_snapshot(self, tmp_path: Path) -> None:
        assert self._drawn(tmp_path, source="GitHub")["source"] == "GitHub"

    def test_a_machine_without_a_source_has_none(self, tmp_path: Path) -> None:
        assert "source" not in self._drawn(tmp_path)

    def test_an_empty_source_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(MachineDefinitionError, match="source"):
            self._drawn(tmp_path, source="")


class TestContract:
    def test_a_cited_transition_is_a_transition_of_the_api_contract_and_an_uncited_one_stays_bare(self) -> None:
        cite = {"skill": "completing-tasks", "quote": "Only exit 3 is a blocker"}

        cited = Transition.model_validate({"source": "a", "target": "b", "event": "GO", "cite": cite})
        bare = Transition.model_validate({"source": "a", "target": "b", "event": "GO"})

        assert cited.cite == Cite(**cite)
        assert bare.cite is None
