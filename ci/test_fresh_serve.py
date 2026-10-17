"""The fresh-install smoke's checks: which children are alive and what `check` reports."""

from __future__ import annotations

import http.server
import subprocess
import sys
import threading
import time

import pytest
from fresh_serve import check, live_children, worker_contexts

PARENT = (
    "import subprocess, sys, time\n"
    "for argv in sys.argv[1:]:\n"
    "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', *argv.split()])\n"
    "time.sleep(30)\n"
)


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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()


@pytest.fixture
def parent(request):
    proc = subprocess.Popen([sys.executable, "-c", PARENT, *request.param])
    yield proc
    proc.kill()
    proc.wait()


def wait_for_children_named(proc, names):
    deadline = time.monotonic() + 10
    while set(live_children(proc.pid)) != names and time.monotonic() < deadline:
        time.sleep(0.05)


@pytest.mark.parametrize("parent", [("worker pulls", "other thing")], indirect=True)
def test_live_children_names_only_the_worker_children(parent):
    wait_for_children_named(parent, {"pulls"})
    assert set(live_children(parent.pid)) == {"pulls"}


@pytest.mark.parametrize("parent", [("worker pulls", "worker autopilot")], indirect=True)
def test_check_passes_with_the_page_up_and_every_worker_alive(parent, page):
    wait_for_children_named(parent, {"pulls", "autopilot"})
    assert check(page, parent.pid, {"pulls", "autopilot"}) is None


@pytest.mark.parametrize("parent", [("worker pulls",)], indirect=True)
def test_check_names_the_worker_context_with_no_live_child(parent, page):
    wait_for_children_named(parent, {"pulls"})
    assert "autopilot" in check(page, parent.pid, {"pulls", "autopilot"})


@pytest.mark.parametrize("parent", [("worker pulls",)], indirect=True)
def test_check_reports_a_page_that_is_not_200(parent, page):
    Page.status = 503
    try:
        wait_for_children_named(parent, {"pulls"})
        assert "503" in check(page, parent.pid, {"pulls"})
    finally:
        Page.status = 200


def test_worker_contexts_are_the_ones_the_default_config_supervises(tmp_path):
    assert worker_contexts(sys.executable, str(tmp_path)) == {"api", "pulls", "autopilot", "runs", "history", "board"}
