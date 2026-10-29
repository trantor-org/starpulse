"""The fresh-install smoke's checks: which children are alive and what `check` reports."""

from __future__ import annotations

import contextlib
import http.server
import ssl
import sys
import threading
import types

import fresh_serve
import pytest
from fresh_serve import check, live_children, worker_contexts

# A serve (pid 100) whose zygote (pid 200) forks the workers: their ps rows carry the zygote's argv, so the supervisor's
# log is the only record of which pid runs which context. `api` is a plain subprocess of serve.
TABLE = {100: (1, "S"), 200: (100, "S"), 201: (200, "S"), 202: (200, "S"), 300: (100, "S"), 400: (1, "S")}
LOG = """INFO:starpulse:worker pulls started as pid 201
INFO:starpulse:worker board started as pid 202
INFO:starpulse:worker api started as pid 300
"""


@pytest.fixture
def table(monkeypatch):
    rows = dict(TABLE)
    monkeypatch.setattr(fresh_serve, "process_table", lambda: rows)
    return rows


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "serve.log"
    path.write_text(LOG)
    return path


class Page(http.server.BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def page():
    server = http.server.HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield server.server_port
    server.shutdown()


def test_live_children_finds_workers_forked_from_a_zygote(table, log):
    assert live_children(100, log) == {"pulls": 201, "board": 202, "api": 300}


def test_live_children_takes_the_latest_pid_a_restarted_context_logged(table, log):
    log.write_text(LOG + "INFO:starpulse:worker pulls started as pid 203\n")
    table[203] = (200, "S")
    assert live_children(100, log)["pulls"] == 203


def test_live_children_skips_a_dead_zombie_or_foreign_pid(table, log):
    del table[201]
    table[202] = (200, "Zs")
    table[300] = (400, "S")
    assert live_children(100, log) == {}


def test_check_passes_with_the_page_up_and_every_worker_alive(table, log, page):
    assert check(page, 100, {"pulls", "board", "api"}, log) is None


def test_check_names_the_worker_context_with_no_live_child(table, log, page):
    del table[202]
    assert "board" in check(page, 100, {"pulls", "board", "api"}, log)


def test_check_reports_a_page_that_is_not_200(table, log, page):
    Page.status = 503
    try:
        assert "503" in check(page, 100, {"pulls"}, log)
    finally:
        Page.status = 200


def test_worker_contexts_are_the_ones_the_default_config_supervises(tmp_path):
    assert worker_contexts(sys.executable, str(tmp_path)) == {
        "api",
        "pulls",
        "scheduler",
        "runs",
        "flow-metrics",
        "board",
    }


def test_live_children_reads_a_hyphenated_context_name(table, log):
    log.write_text(LOG + "INFO:starpulse:worker flow-metrics started as pid 203\n")
    table[203] = (200, "S")
    assert live_children(100, log)["flow-metrics"] == 203


def test_a_failed_smoke_carries_what_serve_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(fresh_serve, "worker_contexts", lambda python, cwd: set())
    serve = tmp_path / "python"
    serve.write_text('#!/bin/sh\n[ "$3" = migrate ] && exit 0\necho \'cannot hand the socket\' >&2\nexit 3\n')
    serve.chmod(0o755)
    problem = fresh_serve.smoke(str(serve), 5.0)
    assert problem is not None
    assert "serve exited 3" in problem
    assert "cannot hand the socket" in problem


def test_check_reports_a_dead_pulls_worker_as_down(table, log, page):
    del table[201]
    problem = check(page, 100, {"pulls", "board", "api"}, log)
    assert problem is not None
    assert "pulls" in problem
    assert "down" in problem.lower()


def test_check_over_https_takes_any_certificate(table, log, tmp_path, monkeypatch):
    seen = {}

    def urlopen(url, timeout, context):
        seen.update(url=url, verify=context.verify_mode)
        return contextlib.nullcontext(types.SimpleNamespace(status=200))

    monkeypatch.setattr(fresh_serve.urllib.request, "urlopen", urlopen)
    assert check(8766, 100, {"pulls", "board", "api"}, log, "https") is None
    assert seen == {"url": "https://127.0.0.1:8766/", "verify": ssl.CERT_NONE}
