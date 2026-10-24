"""A release ends a claim but remembers the session it ended; the next claim forgets it."""

from starpulse._internal.board.claims import assignee_of, released, released_from, unreleased

_BODY = "## Implementation Notes\n\n<!-- SECTION:NOTES:BEGIN -->\n{notes}\n<!-- SECTION:NOTES:END -->\n"


def test_a_release_drops_the_assignee_and_names_the_session_it_released() -> None:
    body = released(_BODY.format(notes="**Assignee:** dc6921e2"))
    assert (assignee_of(body), released_from(body)) == ("", "dc6921e2")


def test_a_second_release_replaces_the_session_named() -> None:
    first = released(_BODY.format(notes="**Assignee:** dc6921e2"))
    second = released(first.replace("<!-- SECTION:NOTES:END -->", "**Assignee:** 0f0f169a\n<!-- SECTION:NOTES:END -->"))
    assert released_from(second) == "0f0f169a"
    assert second.count("**Released from:**") == 1


def test_a_release_of_an_unheld_body_names_no_one() -> None:
    assert released_from(released(_BODY.format(notes="plain note"))) == ""


def test_unreleased_forgets_the_session_a_release_named() -> None:
    body = unreleased(released(_BODY.format(notes="**Assignee:** dc6921e2\nplain note")))
    assert (released_from(body), "plain note" in body) == ("", True)
