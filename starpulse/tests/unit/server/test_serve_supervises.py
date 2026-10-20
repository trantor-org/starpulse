"""`serve` supervises a `starpulse worker` child for each context whose `*_worker` setting is false, and runs no context's threads itself."""

import threading
from pathlib import Path

import pytest

from starpulse._internal.autopilot.remote import Remote
from starpulse._internal.server import autopilot_service as service
from starpulse._internal.server import server, worker
from starpulse._internal.server.closure import ENTRIES, Reader
from starpulse._internal.server.server import DATABASE_STACK
from starpulse.tests import fake_board
from starpulse.tests.conftest import FakeForker, FakeSupervisor

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


def _serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: str, ending: type[BaseException] | None = None
) -> tuple[dict[str, object], list[str]]:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)

    def end() -> None:
        if ending:
            raise ending

    monkeypatch.setattr(server, "stay_until_stopped", end)
    monkeypatch.setattr(server, "serve_until_stopped", lambda httpd, feed: None)
    threads: list[str] = []
    monkeypatch.setattr(service, "start_autopilot", lambda *args, **kwargs: threads.append("autopilot"))
    monkeypatch.setattr(server, "start_delivery", lambda *args, **kwargs: threads.append("delivery") or (None, None))
    handled: dict[str, object] = {}
    monkeypatch.setattr(server, "request_handler", lambda *args, **kwargs: handled.update(kwargs, services=args[5]))
    config = tmp_path / "starpulse.toml"
    config.write_text(settings + BOARD)

    try:
        server.main(["--config", str(config), "--port", "0"])
    except SystemExit, KeyboardInterrupt:
        pass
    worker.main(["api", "--config", str(config), "--port", "0"])  # the Page API child serve supervises builds the page

    return handled, threads


def test_serve_supervises_every_worker_and_starts_no_context_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    handled, threads = _serve(tmp_path, monkeypatch, "")

    assert threads == []
    assert isinstance(handled["services"].autopilot, Remote)
    [supervisor] = supervisors
    assert set(supervisor.commands) == {"api", "pulls", "autopilot", "runs", "flow-metrics", "board"}
    assert supervisor.started


def test_serve_offers_the_reload_endpoint_beside_its_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    _serve(tmp_path, monkeypatch, "")

    assert supervisors[0].options["control"] == tmp_path / "starpulse.control"
    assert isinstance(supervisors[0].options["read"], Reader)


def test_serve_forks_its_workers_from_one_preloaded_process_it_closes_at_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], forkers: list[FakeForker]
) -> None:
    _serve(tmp_path, monkeypatch, "")

    [forker] = forkers
    assert forker.started
    assert forker.closed
    assert forker.modules == [*DATABASE_STACK, *(ENTRIES[context] for context in supervisors[0].commands)]
    assert forker.listening is not None  # the Page API child forks with the socket it serves
    assert supervisors[0].options["spawn"] is forker
    assert supervisors[0].options["retire"] == forker.retire


@pytest.mark.parametrize(
    ("settings", "supervised"),
    [
        ("api_worker = true\n", {"pulls", "autopilot", "runs", "flow-metrics", "board"}),
        ("runs_worker = true\n", {"api", "pulls", "autopilot", "flow-metrics", "board"}),
        ("flow_metrics_worker = true\n", {"api", "pulls", "autopilot", "runs", "board"}),
        ("board_worker = true\n", {"api", "pulls", "autopilot", "runs", "flow-metrics"}),
        (
            "api_worker = true\nruns_worker = true\nflow_metrics_worker = true\nboard_worker = true\n",
            {"pulls", "autopilot"},
        ),
    ],
)
def test_a_true_worker_setting_gets_neither_a_thread_nor_a_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisors: list[FakeSupervisor],
    settings: str,
    supervised: set[str],
) -> None:
    _, threads = _serve(tmp_path, monkeypatch, settings)

    assert threads == []
    assert set(supervisors[0].commands) == supervised


@pytest.mark.parametrize("ending", [None, KeyboardInterrupt, SystemExit])
def test_serve_stops_its_children_however_it_ends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisors: list[FakeSupervisor],
    ending: type[BaseException] | None,
) -> None:
    _serve(tmp_path, monkeypatch, "", ending)

    assert supervisors[0].stopped


RUNS = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.invalid"\n'


class Dagu:
    """A runs adapter that notes the follow `serve` must leave to the Runs worker, and starts what the page asks."""

    followed: list[str] = []

    @staticmethod
    def start(url: str):
        return lambda workflow: "run-1"

    @classmethod
    def follow(cls, url: str, sink: object, log: object) -> None:
        cls.followed.append(url)


@pytest.mark.parametrize("settings", ["", "runs_worker = true\n"])
def test_serve_follows_no_run_adapter_and_starts_no_pushed_run_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], settings: str
) -> None:
    monkeypatch.setattr(Dagu, "followed", [])
    monkeypatch.setattr(server, "_adapter", lambda parser, instance: Dagu)
    monkeypatch.setattr(server, "PushRuns", lambda *args: pytest.fail("serve follows pushed runs"), raising=False)
    handled, _ = _serve(tmp_path, monkeypatch, settings + RUNS)

    assert Dagu.followed == []
    assert "dagu" in handled["services"].starts  # the page's Run now still reaches the adapter


@pytest.mark.parametrize("settings", ["", "flow_metrics_worker = true\n"])
def test_serve_runs_neither_the_recorder_nor_the_prune_thread_whatever_the_history_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], settings: str
) -> None:
    before = {t.name for t in threading.enumerate()}

    _serve(tmp_path, monkeypatch, settings)

    assert not {"machine-history", "event-log-prune"} & ({t.name for t in threading.enumerate()} - before)


SEARCH = '[search]\nembeddings_url = "http://embeddings.test/v1/embeddings"\nmodel = "m"\n'


@pytest.mark.parametrize(("settings", "supervised"), [("", True), ("search_worker = true\n", False)])
def test_serve_runs_no_embedding_thread_and_supervises_a_search_child_for_a_false_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisors: list[FakeSupervisor],
    settings: str,
    supervised: bool,
) -> None:
    before = {t.name for t in threading.enumerate()}

    _serve(tmp_path, monkeypatch, settings + SEARCH)

    assert "search-embeddings" not in {t.name for t in threading.enumerate()} - before
    assert ("search" in supervisors[0].commands) is supervised


@pytest.mark.parametrize("settings", ["", "board_worker = true\n"])
def test_serve_runs_neither_the_criteria_nor_the_reconcile_thread_whatever_the_board_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], settings: str
) -> None:
    before = set(threading.enumerate())

    _serve(tmp_path, monkeypatch, settings)

    assert not {"board-criteria", "lane-reconcile"} & {t.name for t in set(threading.enumerate()) - before}
