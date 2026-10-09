"""A machine is namespaced `<repo>/<machine>` and merges across repos only when its compiled definition hashes equal."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from starpulse._internal.machines.machine_definition import MachineDefinitionError
from starpulse._internal.machines.machine_namespace import Source, definition, merge

MACHINES = Path(__file__).parent.parent / "fixtures" / "machines"

PULL_REQUEST: dict[str, Any] = yaml.safe_load((MACHINES / "pull_request.yaml").read_text())


def _written(tmp_path: Path, document: dict[str, Any], name: str = "machine.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def _reordered(document: dict[str, Any]) -> dict[str, Any]:
    """The same machine with every mapping and every `from` list written in the opposite order."""
    states = dict(reversed(document["states"].items()))
    events = {
        event: [
            {**transition, "from": list(reversed(transition["from"]))}
            if isinstance(transition["from"], list)
            else transition
            for transition in reversed(transitions)
        ]
        for event, transitions in reversed(document["events"].items())
    }
    bindings = dict(reversed(document["bindings"].items()))
    return {"bindings": bindings, "events": events, "states": states, "name": document["name"]}


class TestTheDefinitionHash:
    def test_reordering_keys_states_events_and_sources_keeps_the_hash(self, tmp_path: Path) -> None:
        original = definition(_written(tmp_path, PULL_REQUEST, "a.yaml"))
        shuffled = definition(_written(tmp_path, _reordered(PULL_REQUEST), "b.yaml"))

        assert shuffled.digest == original.digest

    def test_one_transition_changed_changes_the_hash(self, tmp_path: Path) -> None:
        changed = yaml.safe_load(yaml.safe_dump(PULL_REQUEST))
        changed["events"]["CI_GREEN"] = [{"from": "ci_running", "to": "in_review"}]

        assert (
            definition(_written(tmp_path, changed)).digest
            != definition(_written(tmp_path, PULL_REQUEST, "b.yaml")).digest
        )

    def test_a_changed_source_changes_the_hash(self, tmp_path: Path) -> None:
        local = definition(_written(tmp_path, PULL_REQUEST, "a.yaml"))
        mapped = definition(_written(tmp_path, {**PULL_REQUEST, "source": "GitHub"}, "b.yaml"))

        assert mapped.digest != local.digest

    def test_an_explicit_false_flag_is_the_same_as_none(self, tmp_path: Path) -> None:
        explicit = yaml.safe_load(yaml.safe_dump(PULL_REQUEST))
        explicit["states"]["ci_red"] = {"initial": False}

        assert (
            definition(_written(tmp_path, explicit)).digest
            == definition(_written(tmp_path, PULL_REQUEST, "b.yaml")).digest
        )

    def test_a_changed_guard_changes_the_hash(self, tmp_path: Path) -> None:
        guarded = yaml.safe_load(yaml.safe_dump(PULL_REQUEST))
        guarded["events"]["MERGED"] = [{"from": "ci_green", "to": "merged", "if": "draft"}]

        assert (
            definition(_written(tmp_path, guarded)).digest
            != definition(_written(tmp_path, PULL_REQUEST, "b.yaml")).digest
        )

    def test_a_changed_flow_child_changes_the_parent_hash(self, tmp_path: Path) -> None:
        for name in ("deploy.yaml", "rollout.yaml"):
            (tmp_path / name).write_text((MACHINES / name).read_text())
        before = definition(tmp_path / "deploy.yaml")
        child = yaml.safe_load((tmp_path / "rollout.yaml").read_text())
        child["states"]["extra"] = {}
        (tmp_path / "rollout.yaml").write_text(yaml.safe_dump(child))

        assert definition(tmp_path / "deploy.yaml").digest != before.digest

    def test_a_flow_opening_a_further_flow_is_refused_as_the_compiler_refuses_it(self) -> None:
        with pytest.raises(MachineDefinitionError, match="one level only"):
            definition(MACHINES / "nested.yaml")


def _pull_request_in(tmp_path: Path, repo: str, **changes: Any) -> Source:
    """A pull request machine as `repo` declares it, with `changes` applied over the shared YAML."""
    document = {**yaml.safe_load(yaml.safe_dump(PULL_REQUEST)), **changes}
    return Source(repo, definition(_written(tmp_path, document, f"{repo.replace('/', '_')}.yaml")))


class TestMergingAcrossRepositories:
    def test_equal_yaml_in_two_repositories_merges_under_namespaced_ids(self, tmp_path: Path) -> None:
        merged = merge([_pull_request_in(tmp_path, "acme/api"), _pull_request_in(tmp_path, "acme/web")])

        assert list(merged) == ["pull_request"]
        assert merged["pull_request"].members == ("acme/api/pull_request", "acme/web/pull_request")
        assert merged["pull_request"].drift == ()

    def test_a_one_transition_change_splits_the_repository_and_records_drift(self, tmp_path: Path) -> None:
        events = {**PULL_REQUEST["events"], "CI_GREEN": [{"from": "ci_running", "to": "in_review"}]}
        api, web = _pull_request_in(tmp_path, "acme/api"), _pull_request_in(tmp_path, "acme/web", events=events)
        spare = _pull_request_in(tmp_path, "acme/cli")

        merged = merge([api, web, spare])["pull_request"]

        assert merged.members == ("acme/api/pull_request", "acme/cli/pull_request")
        assert merged.digest == api.definition.digest
        [drift] = merged.drift
        assert drift.source == "acme/web/pull_request"
        assert drift.digest == web.definition.digest
        assert drift.merged_digest == api.definition.digest
        assert drift.added == ("CI_GREEN: ci_running -> in_review",)
        assert drift.removed == ("CI_GREEN: ci_running -> ci_green",)

    def test_a_tie_between_two_definitions_merges_the_smaller_digest(self, tmp_path: Path) -> None:
        events = {**PULL_REQUEST["events"], "CI_GREEN": [{"from": "ci_running", "to": "in_review"}]}
        api, web = _pull_request_in(tmp_path, "acme/api"), _pull_request_in(tmp_path, "acme/web", events=events)

        forward, backward = merge([api, web])["pull_request"], merge([web, api])["pull_request"]

        assert forward == backward
        assert forward.digest == min(api.definition.digest, web.definition.digest)

    def test_machines_of_different_names_stay_apart(self, tmp_path: Path) -> None:
        other = Source("acme/api", definition(MACHINES / "deploy.yaml"))

        merged = merge([_pull_request_in(tmp_path, "acme/api"), other])

        assert sorted(merged) == ["deploy", "pull_request"]

    def test_one_repository_declaring_a_machine_twice_is_refused(self, tmp_path: Path) -> None:
        twice = [_pull_request_in(tmp_path, "acme/api"), _pull_request_in(tmp_path, "acme/api")]

        with pytest.raises(ValueError, match="acme/api/pull_request"):
            merge(twice)
