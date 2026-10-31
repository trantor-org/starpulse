"""A claim is a frontmatter `assignee`; a release ends it but remembers the session it ended; the next claim forgets it.

The notes' `**Assignee:**` marker is still written beside the field (until the markers go) and read when the field is absent.
"""

from starpulse.board.model.claims import assignee_of, released, released_from, unreleased

_BODY = "## Implementation Notes\n\n<!-- SECTION:NOTES:BEGIN -->\n{notes}\n<!-- SECTION:NOTES:END -->\n"


def test_a_release_drops_the_assignee_and_names_the_session_it_released() -> None:
    frontmatter: dict = {}
    body = released(frontmatter, _BODY.format(notes="**Assignee:** dc6921e2"))
    assert (assignee_of(frontmatter, body), released_from(frontmatter, body)) == ("", "dc6921e2")


def test_a_second_release_replaces_the_session_named() -> None:
    frontmatter: dict = {}
    first = released(frontmatter, _BODY.format(notes="**Assignee:** dc6921e2"))
    frontmatter["assignee"] = "0f0f169a"
    second = released(frontmatter, first)
    assert released_from(frontmatter, second) == "0f0f169a"
    assert second.count("**Released from:**") == 1


def test_a_release_of_an_unheld_body_names_no_one() -> None:
    frontmatter: dict = {"released_from": "dc6921e2"}
    assert released_from(frontmatter, released(frontmatter, _BODY.format(notes="plain note"))) == ""


def test_unreleased_forgets_the_session_a_release_named() -> None:
    body = unreleased(released({}, _BODY.format(notes="**Assignee:** dc6921e2\nplain note")))
    assert (released_from({}, body), "plain note" in body) == ("", True)


def test_a_frontmatter_assignee_is_the_assignee_with_no_marker_in_the_notes() -> None:
    assert assignee_of({"assignee": "s-1"}, _BODY.format(notes="plain note")) == "s-1"


def test_a_frontmatter_assignee_outranks_the_marker_in_the_notes() -> None:
    assert assignee_of({"assignee": "s-2"}, _BODY.format(notes="**Assignee:** s-1")) == "s-2"


def test_a_task_with_no_assignee_field_reads_its_last_marker() -> None:
    assert assignee_of({}, _BODY.format(notes="**Assignee:** s-1\n**Assignee:** s-2")) == "s-2"


def test_an_assignee_that_is_a_list_is_a_profile_not_a_session() -> None:
    assert assignee_of({"assignee": ["@agent-standard-high"]}, _BODY.format(notes="plain note")) == ""


def test_a_release_removes_the_assignee_key_and_writes_released_from() -> None:
    frontmatter: dict = {"assignee": "s-1"}
    released(frontmatter, _BODY.format(notes="plain note"))
    assert frontmatter == {"released_from": "s-1"}


def test_a_released_from_field_outranks_the_marker_in_the_notes() -> None:
    body = _BODY.format(notes="**Released from:** s-1")
    assert released_from({"released_from": "s-2"}, body) == "s-2"
