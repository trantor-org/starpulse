"""Installing the bundled skills: where each harness finds them, and what an install may overwrite."""

from pathlib import Path

import pytest

from starpulse._internal.cli import skill_install as skills


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
