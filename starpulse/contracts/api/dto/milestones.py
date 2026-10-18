"""The milestones, docs and retired records."""

from __future__ import annotations

from typing import Any

from starpulse.contracts.api._base import _Api


class TaskRecord(_Api):
    """`GET /api/task/<id>`: the full record of a task from the board's reader, keyed by its editable fields."""

    task: str
    record: dict[str, Any]


class MilestoneRecord(_Api):
    """A milestone as the board's reader gives it: its sections as text and bullet lists, and its whole description."""

    id: str
    title: str
    outcome: str
    specs: list[str]
    adrs: list[str]
    retro: str
    description: str


class Milestones(_Api):
    """`GET /api/milestones`: every open milestone, by ascending number."""

    milestones: list[MilestoneRecord]


class MilestoneShown(_Api):
    """`GET /api/milestones/<id>`: one open milestone."""

    milestone: MilestoneRecord


class DocSummary(_Api):
    """A doc as the board's lister gives it: its front matter and where it is filed, without its body."""

    id: str
    title: str
    type: str
    created_date: str
    updated_date: str
    path: str


class DocRecord(DocSummary):
    """A doc as the board's reader gives it: the summary and the text after its front matter."""

    body: str


class Docs(_Api):
    """`GET /api/docs`: every open doc, by ascending number."""

    docs: list[DocSummary]


class DocShown(_Api):
    """`GET /api/docs/<id>`: one open doc."""

    doc: DocRecord


class RetiredTask(_Api):
    """A retired task as the board's history store keeps it: its id, its file name and the file's text, byte-for-byte."""

    task: str
    name: str
    text: str


class RetiredTasks(_Api):
    """`GET /api/retired[?task=<id>]`: every retired task, or the one `task` names, by id."""

    tasks: list[RetiredTask]
