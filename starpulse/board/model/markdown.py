"""A Task as markdown: a rendering of its record, and the break-glass edit that imports a changed rendering (D5).

The rendering is never state. `render` draws the record; `imported` reads an edited rendering back as the record's
field changes, which the board writes as Events by the operator, marked break-glass. A rendering the reader cannot map
back (a section removed or added, a status changed) is refused whole, naming what it cannot map."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

Record = Mapping[str, Any]

#: The one-line fields under the title, as `- Label: value`, by record field. A list is comma-separated.
_LINES = {
    "type": "Type",
    "priority": "Priority",
    "impact": "Impact",
    "urgency": "Urgency",
    "milestone": "Milestone",
    "labels": "Labels",
    "dependencies": "Dependencies",
    "references": "References",
    "documentation": "Documentation",
    "modifiedFiles": "Modified Files",
}
#: The text sections, each a heading over the field's text.
_TEXT = {
    "description": "Description",
    "plan": "Implementation Plan",
    "notes": "Implementation Notes",
    "finalSummary": "Final Summary",
}
#: The checklist sections: items as `- [ ] #N text`.
_CHECKLISTS = {"acceptanceCriteria": "Acceptance Criteria", "definitionOfDone": "Definition of Done"}
_STATUS = "Status"
_ITEM = re.compile(r"^- \[([ xX])\](?: #(\d+))? ?(.*)$")
_LINE = re.compile(r"^- ([^:]+): ?(.*)$")


class MarkdownRefusedError(ValueError):
    """An edited rendering the import cannot map back to the Task's fields."""


def _joined(value: Any) -> str:
    return ", ".join(value) if isinstance(value, list) else str(value or "")


def render(record: Record) -> str:
    """`record` as markdown: the title, a line per field, then every section, empty ones included so a removal shows."""
    lines = [f"# {record.get('title', '')}", "", f"- {_STATUS}: {record.get('status') or ''}"]
    lines += [f"- {label}: {_joined(record.get(field))}" for field, label in _LINES.items()]
    for field, heading in _TEXT.items():
        lines += ["", f"## {heading}", "", str(record.get(field) or "")]
    for field, heading in _CHECKLISTS.items():
        lines += ["", f"## {heading}", ""]
        lines += [f"- [{'x' if item.get('checked') else ' '}] #{item['n']} {item['text']}" for item in record[field]]
    return "\n".join(lines).rstrip("\n") + "\n"


def _sections(text: str) -> tuple[str, dict[str, str]]:
    """The head above the first `## ` heading and each section's body by heading; a repeated heading is refused."""
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    into = head
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading in sections:
                raise MarkdownRefusedError(f"the section '{heading}' appears twice")
            into = sections[heading] = []
        else:
            into.append(line)
    return "\n".join(head), {heading: "\n".join(body).strip("\n") for heading, body in sections.items()}


def section_get(description: str, heading: str) -> str | None:
    """The body of `description`'s `## <heading>` section, or None when it has none."""
    found = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", description, flags=re.M | re.S)
    return None if found is None else found[1].strip()


def section_set(description: str, heading: str, content: str) -> str:
    """`description` with its `## <heading>` section replaced by `content`, or ending with it when it had none."""
    kept = re.sub(rf"^## {re.escape(heading)}\s*$.*?(?=^## |\Z)", "", description, flags=re.M | re.S)
    return f"{kept.strip()}\n\n## {heading}\n\n{content.strip()}".strip()


def _checklist(body: str, heading: str) -> list[dict[str, Any]]:
    """The items `body` lists, each numbered as it was or new when it has no number; a line that is no item is refused."""
    items = []
    for line in filter(str.strip, body.splitlines()):
        found = _ITEM.match(line)
        if found is None:
            raise MarkdownRefusedError(f"the section '{heading}' holds a line that is no checklist item: {line}")
        mark, number, text = found.groups()
        item = {"text": text, "checked": mark != " "}
        items.append({"n": int(number), **item} if number else item)
    return items


def _same(items: list[dict[str, Any]], before: list[dict[str, Any]]) -> bool:
    return [(item.get("n"), item["text"], item["checked"]) for item in items] == [
        (item["n"], item["text"], bool(item.get("checked"))) for item in before
    ]


def imported(text: str, record: Record) -> dict[str, Any]:
    """The field changes that take `record` to the edited rendering `text`; `{}` when it changed nothing.

    Refused as `MarkdownRefusedError`, naming the section or line: a missing or unknown section, a missing or unknown field
    line, a blank title, or a changed status (a move is a Transition, never an edit).
    """
    head, sections = _sections(text)
    title, lines = _head(head)
    wanted = {*_TEXT.values(), *_CHECKLISTS.values()}
    if missing := [heading for heading in (*_TEXT.values(), *_CHECKLISTS.values()) if heading not in sections]:
        raise MarkdownRefusedError(f"the section '{missing[0]}' was removed; empty it instead of removing it")
    if unknown := [heading for heading in sections if heading not in wanted]:
        raise MarkdownRefusedError(f"the section '{unknown[0]}' is not one a Task has")
    changes: dict[str, Any] = {}
    if title != record.get("title"):
        changes["title"] = title
    for field, label in _LINES.items():
        value = lines.pop(label, None)
        if value is None:
            raise MarkdownRefusedError(f"the line '{label}' was removed; blank it instead of removing it")
        current = record.get(field)
        after: Any = [part.strip() for part in value.split(",") if part.strip()] if isinstance(current, list) else value
        if after != (current if isinstance(current, list) else _joined(current)):
            changes[field] = after
    if (status := lines.pop(_STATUS, None)) is None:
        raise MarkdownRefusedError(f"the line '{_STATUS}' was removed")
    if status != (record.get("status") or ""):
        raise MarkdownRefusedError(f"the line '{_STATUS}' changed; a move is not an edit")
    if lines:
        raise MarkdownRefusedError(f"the line '{next(iter(lines))}' is not a field a Task has")
    for field, heading in _TEXT.items():
        if sections[heading] != str(record.get(field) or "").strip("\n"):
            changes[field] = sections[heading]
    for field, heading in _CHECKLISTS.items():
        items = _checklist(sections[heading], heading)
        if not _same(items, record[field]):
            changes[field] = items
    return changes


def _head(head: str) -> tuple[str, dict[str, str]]:
    """The title and the `- Label: value` lines above the first section."""
    title, lines = None, {}
    for line in filter(str.strip, head.splitlines()):
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        elif found := _LINE.match(line):
            lines[found.group(1).strip()] = found.group(2).strip()
        else:
            raise MarkdownRefusedError(f"the line '{line}' above the sections is not a field")
    if not title:
        raise MarkdownRefusedError("the title is blank")
    return title, lines
