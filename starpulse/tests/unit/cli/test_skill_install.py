"""Installing the bundled skills: where each harness finds them, and what an install may overwrite."""

from pathlib import Path

import pytest
import yaml

from starpulse.cli import skill_install as skills


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A bundle of one skill, so a test can change what the package ships."""
    (tmp_path / "bundle" / "demo").mkdir(parents=True)
    (tmp_path / "bundle" / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: Does a demo.\n---\nv1\n")
    return tmp_path / "bundle"


def test_an_install_copies_each_skill_to_the_harness_directory_and_reports_it_installed(
    tmp_path: Path, source: Path
) -> None:
    root = tmp_path / "project"

    done = skills.install(root, ["claude", "codex"], force=False, source=source)

    assert (root / ".claude/skills/demo/SKILL.md").read_text().endswith("v1\n")
    assert (root / ".agents/skills/demo/SKILL.md").read_text().endswith("v1\n")
    assert [(d["harness"], d["skill"], d["was"]) for d in done] == [
        ("claude", "demo", "absent"),
        ("codex", "demo", "absent"),
    ]
    assert [skills.status(root, h, "demo", source) for h in ("claude", "codex")] == ["installed", "installed"]


def test_a_skill_not_installed_is_absent(tmp_path: Path, source: Path) -> None:
    assert skills.status(tmp_path, "claude", "demo", source) == "absent"


def test_a_copy_edited_since_install_is_modified_and_refused_without_force_leaving_every_harness_untouched(
    tmp_path: Path, source: Path
) -> None:
    skills.install(tmp_path, ["claude"], force=False, source=source)
    copy = tmp_path / ".claude/skills/demo/SKILL.md"
    copy.write_text("mine\n")

    assert skills.status(tmp_path, "claude", "demo", source) == "modified"
    with pytest.raises(ValueError, match=r"\.claude/skills/demo.*--force"):
        skills.install(tmp_path, ["claude", "codex"], force=False, source=source)

    assert copy.read_text() == "mine\n"
    assert skills.status(tmp_path, "codex", "demo", source) == "absent"


def test_force_replaces_a_modified_copy(tmp_path: Path, source: Path) -> None:
    skills.install(tmp_path, ["claude"], force=False, source=source)
    (tmp_path / ".claude/skills/demo/SKILL.md").write_text("mine\n")

    done = skills.install(tmp_path, ["claude"], force=True, source=source)

    assert done[0]["was"] == "modified"
    assert (tmp_path / ".claude/skills/demo/SKILL.md").read_text().endswith("v1\n")
    assert skills.status(tmp_path, "claude", "demo", source) == "installed"


def test_a_directory_the_installer_did_not_write_is_modified(tmp_path: Path, source: Path) -> None:
    (tmp_path / ".claude/skills/demo").mkdir(parents=True)
    (tmp_path / ".claude/skills/demo/SKILL.md").write_text("hand written\n")

    assert skills.status(tmp_path, "claude", "demo", source) == "modified"


def test_a_newer_bundle_makes_an_untouched_copy_outdated_and_a_plain_install_updates_it(
    tmp_path: Path, source: Path
) -> None:
    skills.install(tmp_path, ["claude"], force=False, source=source)
    (source / "demo/SKILL.md").write_text("---\nname: demo\ndescription: Does a demo.\n---\nv2\n")

    assert skills.status(tmp_path, "claude", "demo", source) == "outdated"
    done = skills.install(tmp_path, ["claude"], force=False, source=source)

    assert done[0]["was"] == "outdated"
    assert (tmp_path / ".claude/skills/demo/SKILL.md").read_text().endswith("v2\n")


def test_the_bundle_lists_its_skills_with_their_descriptions(source: Path) -> None:
    assert skills.names(source) == ["demo"]
    assert skills.description("demo", source) == "Does a demo."


VALID_MACHINE = """\
name: demo
states:
  idle: {initial: true}
  review: {role: waiting_on_person}
  done: {final: true}
events:
  SUBMIT:
    - {from: idle, to: review}
  APPROVE:
    - {from: review, to: done}
"""


def _declare_machine(source: Path, machine: str | None) -> None:
    """Rewrite the demo skill's SKILL.md to name `machine` beside it, or to name none."""
    declared = f"machine: {machine}\n" if machine else ""
    (source / "demo/SKILL.md").write_text(f"---\nname: demo\ndescription: Does a demo.\n{declared}---\nv1\n")


def test_an_install_copies_a_skills_machine_beside_its_skill(tmp_path: Path, source: Path) -> None:
    _declare_machine(source, "machine.yaml")
    (source / "demo/machine.yaml").write_text(VALID_MACHINE)

    skills.install(tmp_path, ["claude"], force=False, source=source)

    assert (tmp_path / ".claude/skills/demo/machine.yaml").read_text() == VALID_MACHINE


def test_a_skill_with_no_machine_still_installs(tmp_path: Path, source: Path) -> None:
    _declare_machine(source, None)

    skills.install(tmp_path, ["claude"], force=False, source=source)

    assert skills.status(tmp_path, "claude", "demo", source) == "installed"


def test_install_fails_when_a_skill_names_a_missing_machine_and_writes_nothing(tmp_path: Path, source: Path) -> None:
    _declare_machine(source, "machine.yaml")

    with pytest.raises(ValueError, match=r"demo names machine machine\.yaml, which is missing"):
        skills.install(tmp_path, ["claude", "codex"], force=False, source=source)

    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".agents").exists()


def test_install_refuses_a_shipped_machine_with_a_state_that_declares_no_role(tmp_path: Path, source: Path) -> None:
    _declare_machine(source, "machine.yaml")
    (source / "demo/machine.yaml").write_text(VALID_MACHINE.replace("{role: waiting_on_person}", "{}"))

    with pytest.raises(ValueError, match=r"state review declares no role"):
        skills.install(tmp_path, ["claude"], force=False, source=source)

    assert not (tmp_path / ".claude").exists()


def test_install_accepts_a_machine_whose_guard_the_adapter_registers_at_runtime(tmp_path: Path, source: Path) -> None:
    _declare_machine(source, "machine.yaml")
    guarded = VALID_MACHINE.replace("- {from: idle, to: review}", "- {from: idle, to: review, if: ready}")
    (source / "demo/machine.yaml").write_text(guarded)

    skills.install(tmp_path, ["claude"], force=False, source=source)

    assert skills.status(tmp_path, "claude", "demo", source) == "installed"


PHASE_SKILLS = ("starting-task", "tdd", "deliver", "review-fix", "mitigate")


def test_the_bundled_task_phase_skills_install_with_their_machines(tmp_path: Path) -> None:
    skills.install(tmp_path, ["claude"], force=False)

    assert [(tmp_path / f".claude/skills/{name}/machine.yaml").is_file() for name in PHASE_SKILLS] == [True] * len(PHASE_SKILLS)


@pytest.mark.parametrize("name", PHASE_SKILLS)
def test_every_transition_of_a_phase_machine_cites_a_sentence_of_its_own_skill(name: str) -> None:
    skill = (skills.SOURCE / name / "SKILL.md").read_text()
    events = yaml.safe_load((skills.SOURCE / name / "machine.yaml").read_text())["events"]
    cites = [transition["cite"] for transitions in events.values() for transition in transitions]

    assert [c["quote"] for c in cites if c["skill"] != name or c["quote"] not in skill] == []


def test_the_mitigate_machine_reaches_diagnosis_only_once_health_is_green() -> None:
    events = yaml.safe_load((skills.SOURCE / "mitigate" / "machine.yaml").read_text())["events"]

    assert [transition["from"] for transition in events["DIAGNOSED"]] == ["healthy"]
