"""A Task as plain text for a reader at a terminal: its header, every filled section, then its comments.

The text is what `starpulse task show --text` prints. Unlike the markdown rendering it is never read back, so it keeps
the comments and leaves out every empty section.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

_STAMP = "%Y-%m-%d %H:%M"
_RULE = "-" * 50


def _items(items: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(f"- [{'x' if item['checked'] else ' '}] #{item['n']} {item['text']}" for item in items)


def _labelled(stamp: object) -> str:
    """A comment's stamp, labelled with the host's zone."""
    try:
        return f"{stamp} ({datetime.strptime(str(stamp), _STAMP).astimezone().tzname()})"
    except ValueError:
        return str(stamp)


def render(record: Mapping[str, Any], *, done: bool) -> str:
    """`record` as plain text; `done` marks its lane as the finished one."""
    header = [f"Task {record['id']} - {record['title']}", "=" * 50, "", f"Status: {'✔' if done else '○'} {record['status']}"]
    for label, value in (
        ("Tier", record.get("tier") or "standard"),
        ("Type", record.get("type")),
        ("Profile", record.get("profile")),
        ("Holder", record.get("assignee")),
        ("Labels", ", ".join(record.get("labels") or [])),
        ("Milestone", record.get("milestone")),
        ("Depends on", ", ".join(record.get("dependencies") or [])),
        ("References", ", ".join(record.get("references") or [])),
        ("Documentation", ", ".join(record.get("documentation") or [])),
    ):
        if value:
            header.append(f"{label}: {value}")
    body: list[str] = []
    for heading, text in (
        ("Description", record.get("description")),
        ("Acceptance Criteria", _items(record.get("acceptanceCriteria") or [])),
        ("Definition of Done", _items(record.get("definitionOfDone") or [])),
        ("Implementation Plan", record.get("plan")),
        ("Implementation Notes", record.get("notes")),
        ("Final Summary", record.get("finalSummary")),
    ):
        if text:
            body += [f"{heading}:", _RULE, str(text), ""]
    if files := record.get("modifiedFiles"):
        body += [f"Modified files: {', '.join(files)}", ""]
    if plan := record.get("verifyPlan"):
        body += ["Verify plan:", *plan, ""]
    if comments := record.get("comments"):
        body += ["Comments:", _RULE]
        for index, comment in enumerate(comments, 1):
            author = [f"By: {comment['author']}"] if comment.get("author") else []
            body += [f"#{index} - {_labelled(comment['created'])}", *author, comment["text"], ""]
    return "\n".join([*header, "", *body]).rstrip()
