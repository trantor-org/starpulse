"""The Jira adapter on recorded fixtures: a project's workflow in as the Board machine, its issues in as board tasks."""

import copy
import json
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from starpulse._internal.adapters.boards.jira import JiraProject, board, http_fetch, import_workflow, jira_keys
from starpulse._internal.api.adapter_kit import BoardAdapterKit
from starpulse.contracts.adapters import BoardTask

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "jira"
WORKFLOW = "Payments Software Workflow"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Site:
    """A Jira site that replays the recorded responses and remembers each request it was asked."""

    def __init__(self, workflows: dict, pages: dict[str, dict]) -> None:
        self.workflows, self.pages, self.requests = workflows, pages, []

    def respond(self, path: str, query: dict[str, list[str]], auth: str) -> tuple[int, dict]:
        self.requests.append((path, query, auth))
        if path == "/rest/api/2/workflows/search":
            if query.get("workflowName") == [WORKFLOW]:
                return 200, self.workflows
            return 200, {"isLast": True, "values": [], "statuses": []}
        if path == "/rest/api/2/search/jql":
            return 200, self.pages[query.get("nextPageToken", [""])[0]]
        return 404, {"errorMessages": [f"no such resource {path}"]}


@contextmanager
def serve(site: Site) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            status, body = site.respond(parts.path, parse_qs(parts.query), self.headers.get("Authorization", ""))
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def recorded_site() -> Site:
    return Site(fixture("workflows_search"), {"": fixture("search_page_1"), "EgQIlMIC": fixture("search_page_2")})


def project(url: str, project: str = "PAY") -> JiraProject:
    return JiraProject(http_fetch(url, "Bearer s3cret"), project, WORKFLOW)


def scanned(jira: JiraProject) -> list[BoardTask]:
    put: list[BoardTask] = []
    jira.scan(put.append, lambda task: None)
    return put


class TestJiraBoardAdapter(BoardAdapterKit):
    keys = jira_keys("PAY")
    teams = {"PAY-1": "PAY", "PAY-2": "PAY", "PAY-3": "PAY", "PAY-4": "PAY"}
    branches = {"feature/PAY-12-add-x": "PAY-12", "refs/heads/PAY-3": "PAY-3", "main": None, "PAY-x": None}

    @pytest.fixture(autouse=True)
    def _site(self) -> Iterator[None]:
        with serve(recorded_site()) as url:
            self.url = url
            self.machines = {"board": project(url).machine}
            yield

    def produce(self) -> list[dict]:
        """Every task one fresh scan of the site puts."""
        return [task.model_dump(mode="json") for task in scanned(project(self.url))]


def test_the_imported_workflow_compiles_to_the_board_machine_of_its_jira_statuses() -> None:
    drawn, done = import_workflow(fixture("workflows_search"), WORKFLOW)

    assert [(s["id"], s["name"], s["initial"], s["final"]) for s in drawn["states"]] == [
        ("to_do", "To Do", True, False),
        ("in_progress", "In Progress", False, False),
        ("in_review", "In Review", False, False),
        ("done", "Done", False, True),
    ]
    assert drawn["mainLine"] == ["to_do", "in_progress", "in_review", "done"]
    assert done == {"done"}


def test_the_machines_transitions_are_the_workflows_directed_and_global_ones() -> None:
    drawn, _ = import_workflow(fixture("workflows_search"), WORKFLOW)

    edges = {(t["source"], t["target"], t["event"]) for t in drawn["transitions"]}
    assert edges == {
        ("to_do", "in_progress", "START_WORK"),
        ("in_progress", "in_review", "REQUEST_REVIEW"),
        ("in_review", "done", "APPROVE"),
        ("in_review", "in_progress", "REQUEST_CHANGES"),
        ("done", "to_do", "REOPEN"),
        ("to_do", "done", "CLOSE"),
        ("in_progress", "done", "CLOSE"),
        ("in_review", "done", "CLOSE"),
    }


def test_a_status_outside_every_transition_is_refused_naming_it() -> None:
    page = fixture("workflows_search")
    page["statuses"].append(
        {"id": "10004", "name": "Blocked", "statusCategory": "IN_PROGRESS", "statusReference": "10004"}
    )
    page["values"][0]["statuses"].append({"deprecated": False, "properties": {}, "statusReference": "10004"})

    with pytest.raises(ValueError, match="Blocked"):
        import_workflow(page, WORKFLOW)


def test_a_workflow_the_site_does_not_return_is_refused_naming_it() -> None:
    with pytest.raises(ValueError, match="Nope Workflow"):
        import_workflow(fixture("workflows_search"), "Nope Workflow")


def test_a_workflow_with_no_initial_transition_is_refused() -> None:
    page = fixture("workflows_search")
    page["values"][0]["transitions"] = [t for t in page["values"][0]["transitions"] if t["type"] != "INITIAL"]

    with pytest.raises(ValueError, match=WORKFLOW):
        import_workflow(page, WORKFLOW)


def test_two_statuses_that_make_one_lane_are_refused_naming_both() -> None:
    page = copy.deepcopy(fixture("workflows_search"))
    page["statuses"][2]["name"] = "in progress"

    with pytest.raises(ValueError, match=r"In Progress.*in progress|in progress.*In Progress"):
        import_workflow(page, WORKFLOW)


def test_a_scan_reads_every_page_of_the_projects_issues_with_the_credentials() -> None:
    site = recorded_site()
    with serve(site) as url:
        tasks = scanned(project(url))

    assert [t.id for t in tasks] == ["PAY-1", "PAY-2", "PAY-3", "PAY-4"]
    searches = [query for path, query, _ in site.requests if path == "/rest/api/2/search/jql"]
    assert [q.get("nextPageToken") for q in searches] == [None, ["EgQIlMIC"]]
    assert {auth for _, _, auth in site.requests} == {"Bearer s3cret"}
    assert searches[0]["jql"] == ['project = "PAY" ORDER BY key ASC']


def test_a_task_carries_what_its_issue_says() -> None:
    with serve(recorded_site()) as url:
        by_id = {t.id: t for t in scanned(project(url))}

    pay1 = by_id["PAY-1"]
    assert (pay1.title, pay1.lane, pay1.assignee, pay1.labels) == (
        "Capture card payments",
        "to_do",
        "Ada Lovelace",
        ("spike", "cards"),
    )
    assert pay1.description == "Accept a card payment end to end."
    assert pay1.created_at == 1790612100.0  # 2026-09-28T09:15 MST
    assert (by_id["PAY-2"].assignee, by_id["PAY-2"].description) == ("", "")


def test_only_the_issues_a_task_is_blocked_by_are_its_dependencies() -> None:
    with serve(recorded_site()) as url:
        by_id = {t.id: t for t in scanned(project(url))}

    assert by_id["PAY-1"].dependencies == ("PAY-2",)  # PAY-2 blocks PAY-1; the Relates link is no dependency
    assert by_id["PAY-2"].dependencies == ()  # PAY-2 blocks PAY-1, so waits on nothing
    assert by_id["PAY-4"].dependencies == ()


def test_an_issue_in_a_done_status_is_settled_when_it_was_resolved() -> None:
    with serve(recorded_site()) as url:
        by_id = {t.id: t for t in scanned(project(url))}

    assert (by_id["PAY-3"].settled, by_id["PAY-3"].settled_at, by_id["PAY-3"].moves) == ("completed", 1790897400.0, {})
    assert by_id["PAY-1"].settled is None and by_id["PAY-1"].settled_at is None


def test_a_task_in_a_lane_offers_the_moves_the_workflow_allows_from_it() -> None:
    with serve(recorded_site()) as url:
        by_id = {t.id: t for t in scanned(project(url))}

    assert sorted(by_id["PAY-4"].moves) == ["done", "in_progress"]  # Approve, Close and Request changes
    assert sorted(by_id["PAY-1"].moves) == ["done", "in_progress"]


def test_a_second_scan_puts_only_what_changed_and_retracts_what_the_project_lost() -> None:
    site = recorded_site()
    with serve(site) as url:
        jira = project(url)
        put: list[BoardTask] = []
        retracted: list[str] = []
        jira.scan(put.append, retracted.append)
        put.clear()
        site.pages["EgQIlMIC"]["issues"].pop()  # PAY-4 leaves the project
        site.pages[""]["issues"][1]["fields"]["status"]["name"] = "In Review"
        jira.scan(put.append, retracted.append)

    assert [(t.id, t.lane) for t in put] == [("PAY-2", "in_review")]
    assert retracted == ["PAY-4"]


def test_an_issue_whose_status_is_not_in_the_workflow_is_skipped_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    site = recorded_site()
    site.pages[""]["issues"][0]["fields"]["status"]["name"] = "Triage"
    with serve(site) as url, caplog.at_level(logging.WARNING, logger="starpulse._internal.adapters.boards.jira"):
        jira = project(url)
        assert [t.id for t in scanned(jira)] == ["PAY-2", "PAY-3", "PAY-4"]
        scanned(jira)

    assert [r.getMessage() for r in caplog.records] == [
        "PAY-1: status 'Triage' is not in the workflow's statuses; issue skipped"
    ]


def test_a_site_that_does_not_answer_is_refused_when_the_board_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_TEST_TOKEN", "s3cret")

    with pytest.raises(ValueError, match=r"jira site http://127\.0\.0\.1:9"):
        board({**BOARD, "url": "http://127.0.0.1:9"}, Path("."))


BOARD = {"project": "PAY", "workflow": WORKFLOW, "token_env": "JIRA_TEST_TOKEN"}


def test_the_board_draws_the_imported_machine_and_feeds_the_projects_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_TEST_TOKEN", "s3cret")
    placed = threading.Event()
    put: list[BoardTask] = []

    class Feed:
        def put(self, task: BoardTask) -> None:
            put.append(task)
            if len(put) == 3:
                placed.set()

        def retract(self, task: str) -> None:
            raise AssertionError(task)

    with serve(recorded_site()) as url:
        built = board({**BOARD, "url": url, "interval": 3600}, Path("."))
        built.start(Feed(), "test", None)  # type: ignore[arg-type]
        assert placed.wait(10)

    assert sorted(t.id for t in put)[:3] == ["PAY-1", "PAY-2", "PAY-3"]
    assert list(built.machines(lambda name: name, ())) == ["board"]
    assert built.keys is not None and built.keys.for_branch("feature/PAY-9-x") == "PAY-9"
    assert built.writer is None


def test_a_cloud_user_signs_in_with_basic_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_TEST_TOKEN", "s3cret")
    site = recorded_site()
    with serve(site) as url:
        board({**BOARD, "url": url, "user": "ada@example.com"}, Path("."))

    assert {auth for _, _, auth in site.requests} == {"Basic YWRhQGV4YW1wbGUuY29tOnMzY3JldA=="}


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"url": "http://x", "project": "PAY"}, "needs workflow"),
        ({"url": "http://x", "project": "PAY", "workflow": "w", "colour": 1}, "unknown key.*colour"),
        ({"url": "file:///etc/passwd", "project": "PAY", "workflow": "w"}, "not an http or https URL"),
        (
            {"url": "http://x", "project": "PAY", "workflow": "w", "token_env": "JIRA_UNSET_TOKEN"},
            r"\$JIRA_UNSET_TOKEN holds no Jira token",
        ),
    ],
)
def test_a_board_setting_that_cannot_work_is_refused(
    monkeypatch: pytest.MonkeyPatch, settings: dict, message: str
) -> None:
    monkeypatch.delenv("JIRA_UNSET_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_TOKEN", "s3cret")

    with pytest.raises(ValueError, match=message):
        board(settings, Path("."))
