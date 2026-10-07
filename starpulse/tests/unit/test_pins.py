"""A merge in a repository the parent pins applies through the first parent merge whose pin bump includes it."""

from __future__ import annotations

import subprocess

import pytest

from starpulse.settings.config import Repo
from starpulse.settings.pins import GitHub, contained, link

REPOS = (Repo(name="skills", path="skills", applied_by="pin-bump"),)
CHILD_SHA, LATER_SHA = "c1" * 20, "c2" * 20
OLD_POINTER, NEW_POINTER = "a0" * 20, "d0" * 20


def pull(repo: str, number: int, sha: str, merged_at: str) -> tuple[str, dict]:
    url = f"https://github.com/trantor-org/{repo}/pull/{number}"
    return url, {"number": number, "url": url, "merged": True, "merge_sha": sha, "merged_at": merged_at}


def pulls(*records: tuple[str, dict]) -> dict[str, dict]:
    return dict(records)


class Git:
    """A parent's pin history: each parent merge's pointer at `skills`, and which pointers contain which child merge."""

    def __init__(self, pointers: dict[str, str | None], containing: dict[str, set[str]]) -> None:
        self.pointers, self.containing, self.asked = pointers, containing, []

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        self.asked.append((repo, sha, path))
        return self.pointers.get(sha)

    def reaches(self, repo: str, sha: str, at: str) -> bool:
        return sha in self.containing.get(at, set())


def linked(records: dict[str, dict], git: Git) -> dict[str, dict]:
    return link(records, REPOS, git.pointer, git.reaches)


def test_a_child_merge_links_to_the_first_parent_merge_whose_pin_bump_includes_it() -> None:
    child_url, child = pull("skills", 7, CHILD_SHA, "2026-10-07T10:00:00Z")
    records = pulls(
        (child_url, child),
        pull("trantor", 1, "p1" * 20, "2026-10-07T09:00:00Z"),
        pull("trantor", 2, "p2" * 20, "2026-10-07T11:00:00Z"),
        pull("trantor", 3, "p3" * 20, "2026-10-07T12:00:00Z"),
        pull("trantor", 4, "p4" * 20, "2026-10-07T13:00:00Z"),
    )
    git = Git(
        {"p1" * 20: OLD_POINTER, "p2" * 20: OLD_POINTER, "p3" * 20: NEW_POINTER, "p4" * 20: NEW_POINTER},
        {NEW_POINTER: {CHILD_SHA}},
    )

    assert linked(records, git)[child_url]["applied_by"] == "p3" * 20
    assert ("trantor-org/trantor", "p1" * 20, "skills") not in git.asked


def test_a_child_merge_stays_unapplied_until_a_parent_merge_pins_it() -> None:
    child_url, child = pull("skills", 7, CHILD_SHA, "2026-10-07T10:00:00Z")
    records = pulls((child_url, child), pull("trantor", 2, "p2" * 20, "2026-10-07T11:00:00Z"))

    assert linked(records, Git({"p2" * 20: OLD_POINTER}, {}))[child_url]["applied_by"] is None


def test_a_parent_merge_whose_pointer_cannot_be_read_does_not_apply_the_child() -> None:
    child_url, child = pull("skills", 7, CHILD_SHA, "2026-10-07T10:00:00Z")
    records = pulls((child_url, child), pull("trantor", 2, "p2" * 20, "2026-10-07T11:00:00Z"))

    assert linked(records, Git({"p2" * 20: None}, {}))[child_url]["applied_by"] is None


def test_a_merge_in_a_repository_the_parent_does_not_pin_carries_no_link() -> None:
    url, record = pull("trantor", 2, "p2" * 20, "2026-10-07T11:00:00Z")

    assert "applied_by" not in linked(pulls((url, record)), Git({}, {}))[url]


def test_a_child_pull_request_that_has_not_merged_carries_no_link() -> None:
    url, record = pull("skills", 8, CHILD_SHA, "2026-10-07T10:00:00Z")
    record |= {"merged": False, "merge_sha": None, "merged_at": None}

    assert "applied_by" not in linked(pulls((url, record)), Git({}, {}))[url]


class Gh:
    """A `gh api` stand-in: each endpoint's answer, and the endpoints asked."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers, self.asked = answers, []

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.asked.append(command[2])
        answer = self.answers.get(command[2], "")
        return subprocess.CompletedProcess(command, 0 if answer else 1, answer, "")


def test_the_pointer_a_parent_merge_pins_is_read_once_and_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = Gh({"repos/trantor-org/trantor/contents/skills?ref=p1": NEW_POINTER})
    monkeypatch.setattr(subprocess, "run", gh)
    github = GitHub()

    assert [github.pointer("trantor-org/trantor", "p1", "skills") for _ in range(2)] == [NEW_POINTER] * 2
    assert len(gh.asked) == 1


def test_an_unreadable_pointer_is_asked_again_rather_than_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = Gh({})
    monkeypatch.setattr(subprocess, "run", gh)
    github = GitHub()

    assert [github.pointer("trantor-org/trantor", "p1", "skills") for _ in range(2)] == [None, None]
    assert len(gh.asked) == 2


@pytest.mark.parametrize(
    ("status", "contained"), [("ahead", True), ("identical", True), ("behind", False), ("diverged", False)]
)
def test_a_pointer_contains_a_merge_when_it_is_that_commit_or_ahead_of_it(
    monkeypatch: pytest.MonkeyPatch, status: str, contained: bool
) -> None:
    monkeypatch.setattr(
        subprocess, "run", Gh({f"repos/trantor-org/skills/compare/{CHILD_SHA}...{NEW_POINTER}": status})
    )

    assert GitHub().reaches("trantor-org/skills", CHILD_SHA, NEW_POINTER) is contained


def test_a_gh_that_cannot_run_answers_that_nothing_is_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(command: list[str], **_: object) -> None:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", missing)

    assert GitHub().pointer("trantor-org/trantor", "p1", "skills") is None


def page(*commits: tuple[str, str], more: bool = False) -> dict:
    return {
        "history": {
            "pageInfo": {"hasNextPage": more},
            "nodes": [{"oid": oid, "committedDate": date} for oid, date in commits],
        }
    }


MERGED_AT = "2026-10-07T10:00:00Z"


@pytest.mark.parametrize(
    ("history", "answer"),
    [
        (page(("a" * 40, "2026-10-07T12:00:00Z"), (CHILD_SHA, MERGED_AT)), True),
        (page(("a" * 40, "2026-10-07T12:00:00Z"), (CHILD_SHA, MERGED_AT), more=True), True),
        (page(("a" * 40, "2026-10-07T09:00:00Z"), more=True), False),
        (page(("a" * 40, "2026-10-07T12:00:00Z"), ("b" * 40, "2026-10-07T09:00:00Z")), False),
        (page(("a" * 40, "2026-10-07T12:00:00Z"), ("b" * 40, "2026-10-07T11:00:00Z"), more=True), None),
        (page(("a" * 40, MERGED_AT), more=True), None),
        (page(), None),
        (None, None),
    ],
    ids=[
        "in a whole page",
        "in a full page",
        "not in a page that reaches back past the merge",
        "not in a page that holds the whole history",
        "older than a full page",
        "as old as a full page's oldest commit",
        "empty page",
        "pointer GitHub could not read",
    ],
)
def test_a_history_page_says_whether_it_holds_a_merge_or_is_too_short_to_tell(
    history: dict | None, answer: bool | None
) -> None:
    assert contained(CHILD_SHA, MERGED_AT, history) is answer


def test_answers_learned_from_the_batched_read_are_never_asked_of_gh_and_are_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = Gh({})
    monkeypatch.setattr(subprocess, "run", gh)
    github = GitHub()

    github.learn(
        {("trantor-org/trantor", "p1", "skills"): NEW_POINTER}, {("trantor-org/skills", CHILD_SHA, NEW_POINTER): True}
    )

    assert github.pointer("trantor-org/trantor", "p1", "skills") == NEW_POINTER
    assert github.reaches("trantor-org/skills", CHILD_SHA, NEW_POINTER) is True
    assert gh.asked == []
    assert github.answers() == {
        "pointers": [["trantor-org/trantor", "p1", "skills", NEW_POINTER]],
        "reaches": [["trantor-org/skills", CHILD_SHA, NEW_POINTER, True]],
    }
