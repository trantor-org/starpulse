"""The typed brief a create or an edit takes in place of a prose description, and the sections it renders to.

The fields are input only: `Brief.render` writes the `## ` sections the board stores, so a stored description and every
reader of it are unchanged.
"""

from collections.abc import Iterable
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from starpulse.contracts.api._base import _Request

__all__ = ["BlastRadius", "Brief", "Term"]

def _one_line(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("must be one line")
    return value


def _question(value: str) -> str:
    if not value.endswith("?"):
        raise ValueError("must end in a question mark")
    return value


def _text(cap: int | None = None) -> type[str]:
    return Annotated[  # type: ignore[return-value]
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=cap), AfterValidator(_one_line)
    ]


Axis = Annotated[int, Field(ge=0, le=3)]


class BlastRadius(_Request):
    """The four scores, each 0 to 3, and the sentence on the worst axis."""

    reach: Axis
    data: Axis
    undo: Axis
    detect: Axis
    note: _text()


class Term(_Request):
    term: _text()
    meaning: _text()


class Brief(_Request):
    """A task's description as fields; `rollback` is required when `blast_radius.undo` is 2 or more."""

    outcome: _text(200)
    why: _text(400)
    current_state: _text(400)
    scope: Annotated[list[_text(300)], Field(min_length=1)]
    out_of_scope: Annotated[list[_text(300)], Field(min_length=1)]
    blast_radius: BlastRadius
    stop_conditions: Annotated[list[_text()], Field(min_length=1)]
    rollback: _text() | None = None
    terms: list[Term] | None = None
    example: str | None = None
    open_questions: list[Annotated[_text(), AfterValidator(_question)]] | None = None
    cited: list[_text()] | None = None

    @model_validator(mode="after")
    def _rollback_for_a_hard_undo(self) -> Brief:
        if self.blast_radius.undo >= 2 and not self.rollback:
            raise ValueError("rollback is required when blast_radius.undo is 2 or more")
        return self

    def render(self, follows: str | None) -> str:
        """The description's sections in template order; `follows` is the finished task this one picks up from."""
        radius = self.blast_radius
        sections = [
            ("Outcome", self.outcome),
            ("Why", self.why),
            ("Follows", follows),
            ("Current State", self.current_state),
            ("Terms", _bullets(f"**{t.term}**: {t.meaning}" for t in self.terms or ())),
            ("Example", self.example),
            ("Scope", _bullets(self.scope)),
            ("Out of Scope", _bullets(self.out_of_scope)),
            (
                "Blast Radius",
                f"reach {radius.reach} · data {radius.data} · undo {radius.undo} · detect {radius.detect}. {radius.note}",
            ),
            ("Rollback", self.rollback),
            ("Stop Conditions", _bullets(self.stop_conditions)),
            ("Open Questions", _bullets(self.open_questions or ())),
            ("Cited", _bullets(self.cited or ())),
        ]
        return "\n\n".join(f"## {name}\n\n{body}" for name, body in sections if body)


def _bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)

