"""`serve` supervises a `starpulse worker` child for each context whose `*_worker` setting is false, and runs no context's threads itself."""

import threading
from pathlib import Path

import pytest

from starpulse._internal.autopilot.remote import Remote
from starpulse._internal.server import autopilot_service as service
from starpulse._internal.server import server
from starpulse._internal.server.closure import Reader
from starpulse.tests import fake_board
from starpulse.tests.conftest import FakeSupervisor

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


def _serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: str, ending: type[BaseException] | None = None
) -> tuple[dict[str, object], list[str]]:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)

    def end(httpd: object, feed: object) -> None:
        if ending:
            raise ending

    monkeypatch.setattr(server, "serve_until_stopped", end)
    threads: list[str] = []
    monkeypatch.setattr(service, "start_autopilot", lambda *args, **kwargs: threads.append("autopilot"))
    monkeypatch.setattr(server, "start_delivery", lambda *args, **kwargs: threads.append("delivery") or (None, None))
    handled: dict[str, object] = {}
    monkeypatch.setattr(server, "request_handler", lambda *args, **kwargs: handled.update(kwargs, args=args))
    config = tmp_path / "starpulse.toml"
    config.write_text(settings + BOARD)

    try:
        server.main(["--config", str(config), "--port", "0"])
    except SystemExit, KeyboardInterrupt:
        pass

    return handled, threads


def test_serve_supervises_every_worker_and_starts_no_context_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    handled, threads = _serve(tmp_path, monkeypatch, "")

    assert threads == []
    assert isinstance(handled["autopilot"], Remote)
    [supervisor] = supervisors
    assert set(supervisor.commands) == {"pulls", "autopilot", "runs", "history", "board"}
    assert supervisor.started


def test_serve_offers_the_reload_endpoint_beside_its_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    _serve(tmp_path, monkeypatch, "")

    assert supervisors[0].options["control"] == tmp_path / "starpulse.control"
    assert isinstance(supervisors[0].options["read"], Reader)


@pytest.mark.parametrize(
    ("settings", "supervised"),
    [
        ("delivery_worker = true\n", {"autopilot", "runs", "history", "board"}),
        ("autopilot_worker = true\n", {"pulls", "runs", "history", "board"}),
        ("runs_worker = true\n", {"pulls", "autopilot", "history", "board"}),
        ("history_worker = true\n", {"pulls", "autopilot", "runs", "board"}),
        ("board_worker = true\n", {"pulls", "autopilot", "runs", "history"}),
        (
            "delivery_worker = true\nautopilot_worker = true\nruns_worker = true\nhistory_worker = true\n"
            "board_worker = true\n",
            set(),
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


RUNS = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.invalid"\n[[triggers]]\non = "lane"\nstart = "dagu/reconcile"\n'


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
def test_serve_follows_no_run_adapter_and_starts_no_trigger_or_pushed_run_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], settings: str
) -> None:
    monkeypatch.setattr(Dagu, "followed", [])
    monkeypatch.setattr(server, "_adapter", lambda parser, instance: Dagu)
    monkeypatch.setattr(server, "PushRuns", lambda *args: pytest.fail("serve follows pushed runs"), raising=False)
    before = {t.name for t in threading.enumerate()}

    handled, _ = _serve(tmp_path, monkeypatch, settings + RUNS)

    assert Dagu.followed == []
    assert "board-triggers" not in {t.name for t in threading.enumerate()} - before
    assert "dagu" in handled["args"][2]  # the page's Run now still reaches the adapter


FORWARD = '[forward]\nurl = "https://hub.example.test"\ntoken_env = "HUB_TOKEN"\n'


@pytest.mark.parametrize(("settings", "supervised"), [("", True), ("forwarding_worker = true\n", False)])
def test_serve_runs_no_forwarder_thread_and_supervises_a_forwarding_child_for_a_false_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supervisors: list[FakeSupervisor],
    settings: str,
    supervised: bool,
) -> None:
    monkeypatch.setenv("HUB_TOKEN", "secret")
    before = {t.name for t in threading.enumerate()}

    handled, _ = _serve(tmp_path, monkeypatch, settings + FORWARD)

    assert "forwarder" not in {t.name for t in threading.enumerate()} - before
    assert ("forwarding" in supervisors[0].commands) is supervised
    assert handled["forwarding"] is not None  # the page still reads and sets the forwarding opt-in


@pytest.mark.parametrize("settings", ["", "history_worker = true\n"])
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
