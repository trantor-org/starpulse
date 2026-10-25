"""Read a machine from its YAML file: parse it, validate it against `machine.schema.json`, and compile it.

An error cites the file and the line of the value the schema or the compiler refuses.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, best_match

from starpulse.machine_engine.model.machine_definition import (
    Compiled,
    MachineDefinitionError,
    Registry,
    compile_document,
)
from starpulse.machine_engine.model.machine_namespace import Definition, definition_of

__all__ = ["definition", "load_machine", "validate"]

SCHEMA = json.loads((Path(__file__).parents[2] / "schemas" / "machine.schema.json").read_text())
_VALIDATOR = Draft202012Validator(SCHEMA)


def _schema_error(document: Any) -> ValidationError | None:
    return best_match(_VALIDATOR.iter_errors(document))


def _describe(error: ValidationError) -> str:
    where = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{where}: {error.message}"


def validate(document: Any) -> None:
    """Refuse a document the published schema rejects."""
    if (error := _schema_error(document)) is not None:
        raise MachineDefinitionError(_describe(error))


def _line_of(text: str, parts: Iterable[str | int]) -> int:
    """The 1-based line of the YAML value at `parts`, or of the deepest enclosing node that exists."""
    node = yaml.compose(text)
    for part in parts:
        if isinstance(node, yaml.MappingNode):
            child = next((value for key, value in node.value if key.value == part), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            child = node.value[part]
        else:
            child = None
        if child is None:
            break
        node = child
    return node.start_mark.line + 1


def load_machine(path: Path, registry: Registry = Registry()) -> Compiled:
    """Compile the machine file at `path`."""
    return compile_document(_read(path), path, registry)


def _read(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
        document = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as error:
        mark = getattr(error, "problem_mark", None)
        raise MachineDefinitionError(f"{path}: {error}", path, mark.line + 1 if mark else None) from error
    _spell_on(document)
    if isinstance(document, dict) and "subflows" in document:
        raise MachineDefinitionError(
            f"{path}: `subflows:` is now `submachines:`; rename the key", path, _line_of(text, ["subflows"])
        )
    if (error := _schema_error(document)) is not None:
        raise MachineDefinitionError(f"{path}: {_describe(error)}", path, _line_of(text, error.absolute_path))
    return document


def _spell_on(document: Any) -> None:
    """Read a cue's bare `on:` key as the word it is: YAML 1.1 loads it as the boolean `True`."""
    cues = document.get("cues") if isinstance(document, dict) else None
    for cue in cues if isinstance(cues, list) else ():
        if isinstance(cue, dict) and True in cue:
            cue["on"] = cue.pop(True)


def definition(path: Path) -> Definition:
    """The definition of the machine file at `path`."""
    return definition_of(_read(path))
