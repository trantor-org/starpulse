"""The hub's sign-in gate on a running server: every route answers 401 before sign-in, an allowed account signs in
through a mock OpenID Connect issuer container, an account outside the allowed groups is refused with the reason, and
instance and engine tokens never pass for a viewer's session or the other way round, and the reader token reads what a
viewer reads but writes nothing."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("jwt", reason="the hub extras are not installed")

from starpulse._internal.runs.ingest import ForwardIngest, Ingest
from starpulse._internal.server import server
from starpulse._internal.server import writes
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.hub.oidc import ENGINE, INSTANCE, PUBLIC, ROUTE_PREFIXES, ROUTES, SESSION_S, Gate
from starpulse._internal.cli import agent_cli
from starpulse._internal.config.level import Level, Orbit, Terminal
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.level.insights import Insights, InsightStore
from starpulse._internal.config.config import OidcSettings
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse.tests import mock_issuer
from starpulse.tests.machines import MACHINES
from starpulse.tests.mock_issuer import Answer, call, session_of
from starpulse.tests.unit.test_analytics import NOW, ROWS

ALLOWED = ("ops", "admins")
INSTANCE_TOKEN = "cron-secret"
FORWARD_TOKEN = "laptop-secret"
ENGINE_TOKEN = "engine-secret"
READER_TOKEN = "reader-secret"
LEVEL = Level(
    "board", "done", (Terminal("done", "goal"),), gates=("review",), orbit=Orbit("working", ("in_progress", "review"))
)
#: What a sign-in refuses to answer before the viewer has signed in: the sign-in's own two endpoints.
SIGN_IN = {"/auth/login", "/auth/callback"}
#: A route only the engine may call that no handler serves, to see a request pass the gate and reach a 404.
PROBE = "/api/engine-probe"


def documented_routes() -> set[tuple[str, str]]:
    """Every `METHOD /path` the server's two docstrings document, with a path's `<name>` and `?query` parts cut off."""
    found = set()
    pattern = r"\b((?:GET|POST|PUT|DELETE)(?: and DELETE)?)\s+(/[^\s,)]*(?:,\s*/[^\s,)]*)*)"
    for methods, paths in re.findall(pattern, f"{server.__doc__}\n{writes.__doc__}"):
        for path in paths.split(","):
            path = re.sub(r"[<?\[].*", "", path.strip())
            found |= {(method, path) for method in methods.split(" and ")}
    return found


def test_the_documented_routes_include_the_sign_in_and_every_api_family() -> None:
    routes = documented_routes()

    assert {("GET", "/auth/login"), ("GET", "/auth/callback")} <= routes
    assert {("GET", "/api/snapshot"), ("POST", "/api/move"), ("PUT", "/api/history-window")} <= routes
    assert len(routes) >= 20


@dataclass
class Hub:
    server: ThreadingHTTPServer
    issuer: str
    log: EventLog
    redirect_uri: str
    now: list[float]

    def call(
        self, path: str, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None
    ) -> Answer:
        """One request, answered without following a redirect: status, lower-cased headers, body."""
        return call(url(self.server, path), method, headers, data)


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def hub(issuer: str, tmp_path: Path) -> Iterator[Hub]:
    port = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}/auth/callback"
    settings = OidcSettings(
        issuer=issuer,
        client_id="starpulse-hub",
        client_secret_env="HUB_SECRET",
        redirect_uri=redirect_uri,
        allowed_groups=ALLOWED,
    )
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    now = [1_000_000.0]
    gate = Gate(
        settings,
        client_secret="hub-secret",
        engine_token=ENGINE_TOKEN,
        reader_token=READER_TOKEN,
        routes={PROBE: ENGINE},
        clock=lambda: now[0],
    )
    feed = BoardFeed(machines=MACHINES)
    insights = Insights(InsightStore(f"sqlite:///{tmp_path / 'history.sqlite'}"), feed)
    store = HistoryStore(f"sqlite:///{tmp_path / 'level.sqlite'}", MACHINES)
    for i, (task_id, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"a/{i}", task_id, new, at)
    with serve(
        tmp_path,
        feed,
        history=store,
        clock=lambda: NOW,
        level=LEVEL,
        gate=gate,
        ingest=Ingest({"cron": INSTANCE_TOKEN}, log),
        forward=ForwardIngest({"laptop": FORWARD_TOKEN}, log),
        insights=insights,
        port=port,
    ) as running:
        yield Hub(running, issuer, log, redirect_uri, now)


def sign_in(hub: Hub, username: str, groups: list[str]) -> Answer:
    return mock_issuer.sign_in(url(hub.server, ""), hub.issuer, username, groups)


def test_every_documented_route_answers_401_before_sign_in_but_the_sign_in_itself(hub: Hub) -> None:
    refused = {}
    for method, path in sorted(documented_routes() | {("GET", "/no-such-route"), ("GET", "/assets/index-abc123.js")}):
        if path in SIGN_IN:
            continue
        refused[method, path] = hub.call(path, method)[0]
    assert {key: status for key, status in refused.items() if status != 401} == {}


def test_a_method_the_server_does_not_route_answers_401_before_sign_in_too(hub: Hub) -> None:
    for method in ("HEAD", "OPTIONS", "PATCH", "TRACE"):
        assert hub.call("/api/snapshot", method)[0] == 401, method


def test_the_two_sign_in_endpoints_are_the_only_ones_open_before_sign_in(hub: Hub) -> None:
    assert hub.call("/auth/login")[0] == 302
    assert hub.call("/auth/callback")[0] == 400  # no code or state: refused, never an error page that signs anyone in


def test_an_account_in_an_allowed_group_signs_in_and_the_page_and_api_answer(hub: Hub) -> None:
    answer = sign_in(hub, "alice", ["ops", "other"])

    assert answer[0] == 302 and answer[1]["location"] == "/"
    cookie = session_of(answer)
    assert "HttpOnly" in next(c for c in answer[1]["set-cookie"].split("\n") if c.startswith("starpulse_session="))
    assert hub.call("/api/snapshot", headers={"Cookie": cookie})[0] == 200
    assert hub.call("/", headers={"Cookie": cookie})[0] == 200


def test_an_account_outside_the_allowed_groups_is_refused_with_the_reason_and_gets_no_session(hub: Hub) -> None:
    status, headers, body = sign_in(hub, "mallory", ["interns"])

    assert status == 403
    text = body.decode()
    assert "mallory" in text and "not a member of an allowed group" in text
    assert all(group in text for group in ALLOWED)
    assert "set-cookie" not in headers or "starpulse_session" not in headers["set-cookie"]
    assert hub.call("/api/snapshot")[0] == 401


def test_an_account_with_no_groups_claim_is_refused_too(hub: Hub) -> None:
    assert sign_in(hub, "nobody", [])[0] == 403


def test_a_callback_whose_state_the_hub_never_issued_is_refused(hub: Hub) -> None:
    _, headers, _ = hub.call("/auth/login")
    cookie = headers["set-cookie"].partition(";")[0]

    assert hub.call("/auth/callback?code=x&state=forged", headers={"Cookie": cookie})[0] == 400


def test_a_viewer_session_does_not_pass_on_the_instance_ingest_route(hub: Hub) -> None:
    cookie = session_of(sign_in(hub, "alice", ["ops"]))
    event = json.dumps({"phase": "start", "workflow": "cron/nightly", "run_id": "r1", "status": "running"}).encode()
    post = {"Content-Type": "application/json", "Cookie": cookie}

    assert hub.call("/api/runs/events", "POST", post, event)[0] == 401
    assert hub.call("/api/runs/events", "POST", {**post, "Authorization": f"Bearer {INSTANCE_TOKEN}"}, event)[0] == 201


def test_a_viewer_session_does_not_pass_on_the_forward_route_but_a_source_token_does(hub: Hub) -> None:
    cookie = session_of(sign_in(hub, "alice", ["ops"]))
    batch = json.dumps({"opt_in": False, "events": []}).encode()
    post = {"Content-Type": "application/json", "Cookie": cookie}

    assert hub.call("/api/forward", "POST", post, batch)[0] == 401
    assert hub.call("/api/forward", "POST", {**post, "Authorization": f"Bearer {FORWARD_TOKEN}"}, batch)[0] == 200


def test_an_instance_token_does_not_pass_as_a_viewer(hub: Hub) -> None:
    assert hub.call("/api/snapshot", headers={"Authorization": f"Bearer {INSTANCE_TOKEN}"})[0] == 401
    assert hub.call("/", headers={"Authorization": f"Bearer {INSTANCE_TOKEN}"})[0] == 401


def test_the_engine_token_passes_only_on_engine_routes(hub: Hub) -> None:
    engine = {"Authorization": f"Bearer {ENGINE_TOKEN}"}
    instance = {"Authorization": f"Bearer {INSTANCE_TOKEN}"}
    viewer = {"Cookie": session_of(sign_in(hub, "alice", ["ops"]))}

    assert hub.call(PROBE, headers=engine)[0] == 404  # past the gate; no handler serves the probe
    assert hub.call(PROBE, headers=instance)[0] == 401
    assert hub.call(PROBE, headers=viewer)[0] == 401
    assert hub.call(PROBE)[0] == 401
    assert hub.call("/api/snapshot", headers=engine)[0] == 401
    assert hub.call("/api/runs/events", "POST", {**engine, "Content-Type": "application/json"}, b"{}")[0] == 401


FINDING = {
    "id": "slow-review",
    "engine": {"name": "skill-coach", "version": "1.4.0"},
    "scope": {"team": "platform"},
    "severity": "warn",
    "text": "Review takes four times as long as the norm.",
    "created_at": 1_700_000_000.0,
}


def test_the_engine_token_posts_and_retracts_a_finding_through_the_gate(hub: Hub) -> None:
    engine = {"Authorization": f"Bearer {ENGINE_TOKEN}", "Content-Type": "application/json"}

    assert hub.call("/api/insights", "POST", engine, json.dumps(FINDING).encode())[0] == 201
    assert hub.call("/api/insights/slow-review", "DELETE", engine)[0] == 200
    assert hub.call("/api/insights/slow-review", "DELETE", engine)[0] == 404


def test_no_other_credential_reaches_the_insights_routes(hub: Hub) -> None:
    body = json.dumps(FINDING).encode()
    viewer = {"Cookie": session_of(sign_in(hub, "alice", ["ops"]))}
    credentials = {
        "none": {},
        "viewer": viewer,
        "instance": {"Authorization": f"Bearer {INSTANCE_TOKEN}"},
        "wrong engine": {"Authorization": "Bearer not-the-engine-token"},
    }

    for name, headers in credentials.items():
        sent = {**headers, "Content-Type": "application/json"}
        assert hub.call("/api/insights", "POST", sent, body)[0] == 401, name
        assert hub.call("/api/insights/slow-review", "DELETE", sent)[0] == 401, name


def test_the_built_in_routes_open_to_the_gate_are_the_sign_in_the_instance_token_routes_and_the_engine_insights_only() -> (
    None
):
    assert {path for path, access in ROUTES.items() if access == PUBLIC} == SIGN_IN
    assert {path for path, access in ROUTES.items() if access == INSTANCE} == {"/api/runs/events", "/api/forward"}
    assert {path for path, access in ROUTES.items() if access == ENGINE} == {"/api/insights"}
    assert ROUTE_PREFIXES == {"/api/insights/": ENGINE}
    assert set(ROUTES.values()) == {PUBLIC, INSTANCE, ENGINE}


def test_a_session_ends_after_its_lifetime(hub: Hub) -> None:
    cookie = {"Cookie": session_of(sign_in(hub, "alice", ["ops"]))}
    hub.now[0] += SESSION_S - 1
    assert hub.call("/api/snapshot", headers=cookie)[0] == 200

    hub.now[0] += 1

    assert hub.call("/api/snapshot", headers=cookie)[0] == 401


def test_a_started_sign_in_cannot_be_finished_twice(hub: Hub) -> None:
    status, headers, _ = hub.call("/auth/login")
    cookie = headers["set-cookie"].partition(";")[0]
    form = urllib.parse.urlencode({"username": "alice", "claims": json.dumps({"groups": ["ops"]})}).encode()
    _, back, _ = call(headers["location"], "POST", {"Content-Type": "application/x-www-form-urlencoded"}, form)
    callback = urllib.parse.urlsplit(back["location"])
    target = f"{callback.path}?{callback.query}"

    assert hub.call(target, headers={"Cookie": cookie})[0] == 302
    assert hub.call(target, headers={"Cookie": cookie})[0] == 400


READER = {"Authorization": f"Bearer {READER_TOKEN}"}


def test_the_reader_token_reads_the_level_analytics_a_viewer_reads(hub: Hub) -> None:
    for path in ("/api/level?hours=48", "/api/level/trajectories?hours=48", "/api/snapshot", "/"):
        assert hub.call(path)[0] == 401, path
        assert hub.call(path, headers=READER)[0] == 200, path
    assert hub.call("/api/snapshot", "HEAD", READER)[0] != 401


def test_a_wrong_reader_token_is_refused(hub: Hub) -> None:
    assert hub.call("/api/level", headers={"Authorization": "Bearer not-the-reader-token"})[0] == 401


def test_the_reader_token_writes_nothing(hub: Hub) -> None:
    post = {**READER, "Content-Type": "application/json"}
    writes = [
        ("POST", "/api/move"),
        ("PUT", "/api/history-window"),
        ("DELETE", "/api/history-window"),
        ("POST", "/api/runs/events"),
        ("POST", "/api/forward"),
        ("POST", "/api/insights"),
        ("DELETE", "/api/insights/slow-review"),
    ]

    for method, path in writes:
        assert hub.call(path, method, post, b"{}")[0] == 401, (method, path)
    assert hub.call(PROBE, headers=READER)[0] == 401  # an engine route refuses it on a read too


def test_no_other_token_reads_as_the_reader(hub: Hub) -> None:
    for token in (INSTANCE_TOKEN, FORWARD_TOKEN, ENGINE_TOKEN):
        assert hub.call("/api/level", headers={"Authorization": f"Bearer {token}"})[0] == 401, token


def test_the_agent_cli_reads_the_hubs_level_analytics_with_starpulse_token(
    hub: Hub, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["analytics", "trajectories", "--hours", "48", "--server", url(hub.server, "")]

    refused = agent_cli.main(argv, {})
    assert refused == 3 and "401" in capsys.readouterr().out

    assert agent_cli.main(argv, {"STARPULSE_TOKEN": READER_TOKEN}) == 0
    assert "runs" in json.loads(capsys.readouterr().out)
