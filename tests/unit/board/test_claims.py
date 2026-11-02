"""A claim is a frontmatter `assignee`; a release ends it but remembers the session it ended; the next claim forgets it.

The fields alone record a claim: no notes marker is read or written.
"""

from starpulse.board.model.claims import assignee_of, claimed, released, released_from


def test_a_release_drops_the_assignee_and_names_the_session_it_released() -> None:
    frontmatter: dict = {"assignee": "dc6921e2"}
    released(frontmatter)
    assert (assignee_of(frontmatter), released_from(frontmatter)) == ("", "dc6921e2")


def test_a_second_release_replaces_the_session_named() -> None:
    frontmatter: dict = {"assignee": "dc6921e2"}
    released(frontmatter)
    frontmatter["assignee"] = "0f0f169a"
    released(frontmatter)
    assert released_from(frontmatter) == "0f0f169a"


def test_a_release_of_an_unheld_task_names_no_one() -> None:
    frontmatter: dict = {"released_from": "dc6921e2"}
    released(frontmatter)
    assert released_from(frontmatter) == ""


def test_a_claim_forgets_the_session_a_release_named() -> None:
    frontmatter: dict = {"released_from": "dc6921e2"}
    claimed(frontmatter, "s-2")
    assert frontmatter == {"assignee": "s-2"}


def test_an_assignee_that_is_a_list_is_a_profile_not_a_session() -> None:
    assert assignee_of({"assignee": ["@agent-standard-high"]}) == ""


def test_a_release_removes_the_assignee_key_and_writes_released_from() -> None:
    frontmatter: dict = {"assignee": "s-1"}
    released(frontmatter)
    assert frontmatter == {"released_from": "s-1"}
