"""`ApiContract` names every model the route tables do, so a DTO added to one cannot miss `api.schema.json`."""

from __future__ import annotations

import types
import typing
from typing import Any

from pydantic import BaseModel

from starpulse.contracts.api.registry import BODIES, EVENTS, REQUESTS, RESPONSES
from starpulse.contracts.api.schema import ApiContract


def _models(annotation: Any) -> set[type[BaseModel]]:
    """The models an annotation names, through unions and lists."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) in (typing.Union, list):
        return set().union(*(_models(arg) for arg in typing.get_args(annotation)))
    return set()


def test_the_api_contract_names_every_model_the_route_tables_do() -> None:
    tables = {
        model for table in (EVENTS, RESPONSES, REQUESTS, BODIES) for value in table.values() for model in _models(value)
    }
    contract = set().union(*(_models(field.annotation) for field in ApiContract.model_fields.values()))
    assert sorted(m.__name__ for m in tables - contract) == []
    assert sorted(m.__name__ for m in contract - tables) == []
