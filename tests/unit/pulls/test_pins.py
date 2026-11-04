"""A merge in a repository the parent pins applies through the first parent merge whose pin bump includes it."""

from __future__ import annotations

import time

import pytest
from starpulse.pulls.adapters.outbound.pin_reader import _RETRY_WAIT_S, GitHub
from starpulse.pulls.model.pins import Repo, build_commit, contained, link

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
    """A GitHub transport: each endpoint's answer body, the endpoints asked, and the status an unanswered one gets."""

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers, self.asked, self.failure = answers, [], 500

    def __call__(self, method: str, path: str, body: dict | None) -> tuple[int, dict]:
        self.asked.append(path)
        return (200, self.answers[path]) if path in self.answers else (self.failure, {})


def test_the_pointer_a_parent_merge_pins_is_read_once_and_remembered() -> None:
    gh = Gh({"/repos/trantor-org/trantor/contents/skills?ref=p1": {"sha": NEW_POINTER}})
    github = GitHub(transport=gh)

    assert [github.pointer("trantor-org/trantor", "p1", "skills") for _ in range(2)] == [NEW_POINTER] * 2
    assert len(gh.asked) == 1


def test_a_default_branch_head_is_reused_within_its_ttl_then_read_again(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = Gh({"/repos/trantor-org/trantor/commits/HEAD": {"sha": NEW_POINTER}})
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    github = GitHub(transport=gh)

    assert [github.head("trantor-org/trantor") for _ in range(2)] == [NEW_POINTER] * 2
    clock[0] += 61
    github.head("trantor-org/trantor")

    assert len(gh.asked) == 2
    assert github.answers() == {"pointers": [], "reaches": []}


def test_a_failed_read_is_named_by_failing_until_a_later_read_of_it_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    head, contents = "/repos/trantor-org/trantor/commits/HEAD", "/repos/trantor-org/trantor/contents/skills?ref=p1"
    gh = Gh({})
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    github = GitHub(transport=gh)

    github.head("trantor-org/trantor")
    github.pointer("trantor-org/trantor", "p1", "skills")
    assert github.failing() == [head, contents]

    gh.answers = {head: {"sha": NEW_POINTER}, contents: {"sha": NEW_POINTER}}
    clock[0] += 301
    github.head("trantor-org/trantor")
    github.pointer("trantor-org/trantor", "p1", "skills")
    assert github.failing() == []


def failing(status: int) -> Gh:
    """A transport that answers every read with `status` and no body."""
    gh = Gh({})
    gh.failure = status
    return gh


def test_a_path_github_answers_not_found_is_kept_and_saved_rather_than_asked_again() -> None:
    gh = failing(404)
    github = GitHub(transport=gh)

    assert [github.pointer("trantor-org/unraid", "p1", "skills") for _ in range(2)] == [None, None]
    assert len(gh.asked) == 1
    assert github.answers()["pointers"] == [["trantor-org/unraid", "p1", "skills", None]]


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_a_pointer_read_that_fails_without_a_not_found_answer_is_asked_again_only_after_the_retry_wait(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    gh = failing(status)
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    github = GitHub(transport=gh)

    assert [github.pointer("trantor-org/trantor", "p1", "skills") for _ in range(3)] == [None] * 3
    assert len(gh.asked) == 1
    clock[0] += _RETRY_WAIT_S
    assert github.pointer("trantor-org/trantor", "p1", "skills") is None
    assert len(gh.asked) == 2
    assert github.answers()["pointers"] == []


def test_a_compare_that_fails_is_asked_again_only_after_the_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = failing(502)
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    github = GitHub(transport=gh)

    assert [github.reaches("trantor-org/skills", CHILD_SHA, NEW_POINTER) for _ in range(3)] == [False] * 3
    assert len(gh.asked) == 1
    clock[0] += _RETRY_WAIT_S
    github.reaches("trantor-org/skills", CHILD_SHA, NEW_POINTER)
    assert len(gh.asked) == 2


def test_a_compare_that_answers_not_found_answers_not_contained_and_keeps_nothing() -> None:
    github = GitHub(transport=failing(404))

    assert github.reaches("trantor-org/skills", CHILD_SHA, NEW_POINTER) is False
    assert github.answers()["reaches"] == []


def test_a_saved_pointer_that_is_not_a_commit_is_dropped_on_restore_so_the_next_read_settles_it() -> None:
    body = '{"message":"Not Found","status":"404"}'
    github = GitHub(transport=failing(500))

    github.restore(
        {
            "pointers": [
                ["trantor-org/unraid", "p1", "skills", body],
                ["trantor-org/trantor", "p2", "skills", NEW_POINTER],
            ],
            "reaches": [["trantor-org/skills", CHILD_SHA, body, False]],
        }
    )

    assert github.answers() == {"pointers": [["trantor-org/trantor", "p2", "skills", NEW_POINTER]], "reaches": []}


def test_a_path_a_merge_does_not_pin_is_a_remembered_answer_that_is_never_asked_of_github() -> None:
    gh = Gh({})
    github = GitHub(transport=gh)

    github.restore({"pointers": [["trantor-org/unraid", "p1", "skills", None]]})

    assert github.pointer("trantor-org/unraid", "p1", "skills") is None
    assert github.answers()["pointers"] == [["trantor-org/unraid", "p1", "skills", None]]
    assert gh.asked == []


@pytest.mark.parametrize(
    ("status", "contained"), [("ahead", True), ("identical", True), ("behind", False), ("diverged", False)]
)
def test_a_pointer_contains_a_merge_when_it_is_that_commit_or_ahead_of_it(status: str, contained: bool) -> None:
    gh = Gh({f"/repos/trantor-org/skills/compare/{CHILD_SHA}...{NEW_POINTER}": {"status": status}})

    assert GitHub(transport=gh).reaches("trantor-org/skills", CHILD_SHA, NEW_POINTER) is contained


def test_a_transport_that_cannot_connect_answers_that_nothing_is_pinned() -> None:
    def down(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        raise ConnectionError("unreachable")

    assert GitHub(transport=down).pointer("trantor-org/trantor", "p1", "skills") is None


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


@pytest.mark.parametrize(
    ("version", "commit"),
    [
        ("0.4.0.post3+g1a2b3c4", "1a2b3c4"),
        ("0.4.0.post3+g1a2b3c4.d20261019", "1a2b3c4"),
        ("0.4.0", None),
        ("0.4.0+local", None),
        ("0.4.0b2", None),
    ],
)
def test_a_build_carries_its_commit_in_the_local_part_of_its_version(version: str, commit: str | None) -> None:
    assert build_commit(version) == commit


def test_the_default_transport_gets_each_endpoint_as_a_path_with_a_leading_slash() -> None:
    gh = Gh({})
    github = GitHub(transport=gh)

    github.pointer("trantor-org/trantor", "p1", "skills")
    github.head("trantor-org/trantor")
    github.reaches("trantor-org/skills", NEW_POINTER, CHILD_SHA)

    assert len(gh.asked) == 3
    assert all(path.startswith("/repos/") for path in gh.asked)
