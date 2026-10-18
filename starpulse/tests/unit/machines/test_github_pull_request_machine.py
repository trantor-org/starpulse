"""The bundled github-pull-request machine declares the events its writers publish."""

from pathlib import Path

import starpulse
from starpulse._internal.machines.machine_definition import Writer, load_machine, writers_of

BUNDLED = Path(starpulse.__file__).parent / "machines" / "github-pull-request.yaml"


def test_threads_changed_is_a_ci_written_event() -> None:
    compiled = load_machine(BUNDLED)

    assert writers_of(compiled.machine())["THREADS_CHANGED"] == (
        Writer(actor="reviewer", trigger=".github/workflows/review-threads.yml"),
    )
