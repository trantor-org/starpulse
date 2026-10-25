"""D3's seeded board: 20,000 Tasks with 18,000 archived, served from the read model. Every read surface answers a record
within the page's budget, and the board context stays under its configured soft memory limit. Nightly, as the seeded
server's start is budget-sized; `bench/page_latency.py --read-model` is the same board under the full harness.

A surface is judged on its fastest sample here: the work the server does for it. The slower samples carry the
keep-alive round trip every surface pays alike, which is the harness's to judge (`ci/test_page_latency.py`).

The ~60 s is the module fixture, not the reads: 20,000 Task streams appended through `EventStore` and folded by the
`Projector` cost ~140,000 SQLAlchemy statements, about 30 s apiece. Appending them in one transaction measured no
faster, and the board must come through the real store and projector for the budget to mean anything.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import seeded_server
from starpulse._internal.config.config import WORKER_MEMORY
from starpulse._internal.server.page_server import PageServer

pytestmark = [pytest.mark.nightly, pytest.mark.slow]

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = 10

_spec = importlib.util.spec_from_file_location("page_latency", ROOT / "bench" / "page_latency.py")
assert _spec and _spec.loader
pl = sys.modules.setdefault("page_latency", importlib.util.module_from_spec(_spec))
if not hasattr(pl, "time_reads"):
    _spec.loader.exec_module(pl)


def _rss() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise AssertionError("no VmRSS")


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[PageServer, list]]:
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT))
        server, _feed, _tasks = seeded_server.build(
            0,
            tmp_path_factory.mktemp("read-model"),
            read_model=(seeded_server.READ_MODEL_TASKS, seeded_server.READ_MODEL_ARCHIVED),
        )
    server.start()
    rows = pl.time_reads(pl.Client(f"http://127.0.0.1:{server.server_port}"), SAMPLES)
    yield server, rows
    server.close()


def test_every_read_surface_answers_a_record_within_the_budget(served: tuple[PageServer, list]) -> None:
    _, rows = served

    assert not [row.name for row in rows if row.non_2xx]
    assert not [row.name for row in rows if not row.samples], "a surface with no record to read"
    assert {row.name: min(row.samples) for row in rows if min(row.samples) > pl.BUDGET_MS} == {}


def test_the_board_stays_under_its_soft_memory_limit_on_the_seeded_board(served: tuple[PageServer, list]) -> None:
    assert _rss() < WORKER_MEMORY["board"].soft_mb * 1024 * 1024
