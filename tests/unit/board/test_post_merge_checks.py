"""A task's `## Post-merge Checks` block: its schema, and the verdict comment that closes a check."""

import pytest
from starpulse.board.model.post_merge_checks import MARKER, parse, verdict_comment, verdict_of

PASS = "{kind: gh, query: merged}"


def block(check: str) -> str:
    return f"Why\n\n## Post-merge Checks\n\n```yaml\npost_merge_checks:\n{check}\n```\n\n## Other\n\ntext\n"


MINIMAL = f"  - id: a\n    text: t\n    within: 90m\n    pass: {PASS}"


def test_a_valid_block_parses_to_its_checks_with_open_ended_criterion_kinds() -> None:
    checks = parse(block(MINIMAL.replace("kind: gh", "kind: anything-the-client-names")))

    assert checks == [
        {"id": "a", "text": "t", "within": "90m", "pass": {"kind": "anything-the-client-names", "query": "merged"}}
    ]


@pytest.mark.parametrize("body", ["Why\n", "Why\n\n## Other\n\ntext\n", "## Post-merge Checks\n\nprose\n"])
def test_a_body_without_a_block_has_no_checks(body: str) -> None:
    assert parse(body) is None


@pytest.mark.parametrize(
    ("check", "reason"),
    [
        (f"  - text: t\n    within: 1d\n    pass: {PASS}", "id"),
        (f"  - id: a\n    within: 1d\n    pass: {PASS}", "text"),
        ("  - id: a\n    text: t\n    within: 1d", "pass"),
        (f"  - id: a\n    text: t\n    pass: {PASS}", "within"),
        (f"  - id: a\n    text: t\n    within: soon\n    pass: {PASS}", "within"),
        (f"  - id: a\n    text: t\n    within: 0d\n    pass: {PASS}", "within"),
        (f"  - id: a\n    text: t\n    within: 1d\n    pass: {PASS}\n    extra: 1", "extra"),
        ("  - id: a\n    text: t\n    within: 1d\n    pass: [x]", "pass"),
        ("  - id: a\n    text: t\n    within: 1d\n    pass: {query: merged}", "kind"),
        (f"  - id: a\n    text: t\n    within: 1d\n    pass: {PASS}\n    fail: {{kind: 5}}", "fail"),
        ("  - just a string", "mapping"),
        (f"{MINIMAL}\n{MINIMAL}", "duplicate"),
    ],
)
def test_a_malformed_check_is_refused_naming_what_is_wrong(check: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        parse(block(check))


@pytest.mark.parametrize("fence", ["```yaml\npost_merge_checks: [\n```", "```yaml\npost_merge_checks: soon\n```"])
def test_a_block_that_is_not_a_yaml_list_is_refused(fence: str) -> None:
    with pytest.raises(ValueError, match="Post-merge Checks"):
        parse(f"## Post-merge Checks\n\n{fence}\n")


def test_a_verdict_comment_opens_with_the_marker_check_and_verdict_then_the_evidence_and_fix() -> None:
    assert verdict_comment("a", "pass", "up=1") == f"{MARKER} a PASS\nup=1"
    assert verdict_comment("a", "miss", "up=0", fix="TASK-9") == f"{MARKER} a MISS\nFix: TASK-9\nup=0"
    assert verdict_comment("a", "pass") == f"{MARKER} a PASS"


def test_a_check_s_verdict_is_read_from_the_comment_that_opens_with_the_marker() -> None:
    comments = ["note", f"{MARKER} b PASS", f"{MARKER} a MISS\nFix: TASK-9", f"mentions {MARKER} c PASS"]

    assert verdict_of(comments, "a") == "MISS"
    assert verdict_of(comments, "b") == "PASS"
    assert verdict_of(comments, "c") is None
    assert verdict_of(comments, "d") is None
