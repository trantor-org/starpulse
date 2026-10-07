"""Each task's pull requests as the snapshot carries them: read from GitHub, cached, kept when GitHub fails."""

import subprocess
import threading
from collections.abc import Collection

import pytest

from starpulse.adapter_kit import task
from starpulse.board_feed import BoardFeed
from starpulse.config import Repo
from starpulse.pins import GitHub
from starpulse.pull_requests import GhUnavailableError, PullRequests, Pulls, fetch, read_repository

REPO = "https://github.com/acme/widgets/pull"
FIRST, SECOND = f"{REPO}/1750", f"{REPO}/1751"


SHA, MERGED_AT = "9f2c1ab07d3e4f5a6b7c8d9e0f1a2b3c4d5e6f70", "2026-10-06T21:14:09Z"


def _node(
    number: int,
    *,
    rollup: str | None,
    merged: bool = False,
    threads: tuple[bool, ...] = (),
    merge_commit: str | None = None,
    merged_at: str | None = None,
) -> dict:
    """A GraphQL `pullRequest` node: its head commit's check rollup, review threads' resolved flags and merge facts."""
    return {
        "number": number,
        "merged": merged,
        "mergedAt": merged_at,
        "mergeCommit": {"oid": merge_commit} if merge_commit else None,
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": rollup} if rollup else None}}]},
        "reviewThreads": {"nodes": [{"isResolved": resolved} for resolved in threads]},
    }


class _Github:
    """Stands in for GitHub: answers `fetch` with the record it holds per URL, and counts the requests."""

    def __init__(self, **records: dict) -> None:
        self.records = {f"{REPO}/{number.removeprefix('pr')}": record for number, record in records.items()}
        self.requests: list[Collection[str]] = []
        self.down = False
        self.unread: set[str] = set()

    def __call__(self, urls: Collection[str]) -> Pulls:
        self.requests.append(urls)
        if self.down:
            raise GhUnavailableError("gh: network unreachable")
        answer = Pulls({url: self.records[url] for url in urls if url in self.records and url not in self.unread})
        answer.unread = frozenset(self.unread)
        return answer


def _record(
    number: int,
    checks: str,
    *,
    merged: bool = False,
    threads: int = 0,
    stale: bool = False,
    merge_sha: str | None = None,
    merged_at: str | None = None,
) -> dict:
    return {
        "number": number,
        "url": f"{REPO}/{number}",
        "checks": checks,
        "merged": merged,
        "merge_sha": merge_sha,
        "merged_at": merged_at,
        "threads": threads,
        "stale": stale,
    }


def _feed(**tasks: list[str]) -> BoardFeed:
    feed = BoardFeed()
    for name, prs in tasks.items():
        feed.put(task(name.upper().replace("_", "-"), "In Progress", references=prs))
    return feed


def _pulls(feed: BoardFeed) -> dict:
    return feed.snapshot()["pulls"]


def test_the_snapshot_carries_each_tasks_pr_number_check_rollup_merged_state_and_open_thread_count() -> None:
    github = _Github(pr1750=_record(1750, "failing", threads=2), pr1751=_record(1751, "pass", merged=True))
    feed = _feed(proj_7=[FIRST], proj_8=[SECOND])

    PullRequests(feed, github).refresh()

    assert _pulls(feed) == {
        "PROJ-7": [_record(1750, "failing", threads=2)],
        "PROJ-8": [_record(1751, "pass", merged=True)],
    }


def test_a_task_with_several_prs_carries_them_in_the_order_it_cites_them() -> None:
    github = _Github(pr1750=_record(1750, "pass"), pr1751=_record(1751, "pending"))
    feed = _feed(proj_7=[SECOND, FIRST])

    PullRequests(feed, github).refresh()

    assert [pr["number"] for pr in _pulls(feed)["PROJ-7"]] == [1751, 1750]


def test_a_task_with_no_pr_is_not_in_the_map_and_asks_github_for_nothing() -> None:
    github = _Github()
    feed = _feed(proj_7=[])

    PullRequests(feed, github).refresh()

    assert _pulls(feed) == {}
    assert github.requests == []


def test_a_settled_tasks_pr_is_not_asked_for() -> None:
    github = _Github(pr1750=_record(1750, "pass"))
    feed = BoardFeed()
    feed.put(task("PROJ-7", "Done", settled="completed", references=[FIRST]))

    PullRequests(feed, github).refresh()

    assert github.requests == []


def test_snapshots_within_the_refresh_interval_make_no_further_github_request() -> None:
    github = _Github(pr1750=_record(1750, "pass"))
    feed = _feed(proj_7=[FIRST])
    PullRequests(feed, github).refresh()

    for _ in range(3):
        feed.snapshot()
        feed.subscribe()

    assert len(github.requests) == 1


def test_one_refresh_asks_github_once_for_every_open_prs_url() -> None:
    github = _Github(pr1750=_record(1750, "pass"), pr1751=_record(1751, "pass"))
    feed = _feed(proj_7=[FIRST], proj_8=[SECOND])

    PullRequests(feed, github).refresh()

    assert [sorted(urls) for urls in github.requests] == [[FIRST, SECOND]]


def test_a_failed_refresh_keeps_the_last_value_marked_stale() -> None:
    github = _Github(pr1750=_record(1750, "pass", threads=1))
    feed = _feed(proj_7=[FIRST])
    source = PullRequests(feed, github)
    source.refresh()

    github.down = True
    source.refresh()

    assert _pulls(feed) == {"PROJ-7": [_record(1750, "pass", threads=1, stale=True)]}


def test_the_next_good_refresh_clears_the_stale_marker_and_takes_the_new_value() -> None:
    github = _Github(pr1750=_record(1750, "pending"))
    feed = _feed(proj_7=[FIRST])
    source = PullRequests(feed, github)
    source.refresh()
    github.down = True
    source.refresh()

    github.down = False
    github.records[FIRST] = _record(1750, "pass")
    source.refresh()

    assert _pulls(feed) == {"PROJ-7": [_record(1750, "pass")]}


def test_a_refresh_that_fails_before_any_success_leaves_the_map_empty() -> None:
    github = _Github(pr1750=_record(1750, "pass"))
    github.down = True
    feed = _feed(proj_7=[FIRST])

    PullRequests(feed, github).refresh()

    assert _pulls(feed) == {}


def test_a_pr_the_task_no_longer_cites_leaves_the_map_on_the_next_refresh() -> None:
    github = _Github(pr1750=_record(1750, "pass"), pr1751=_record(1751, "pass"))
    feed = _feed(proj_7=[FIRST, SECOND])
    source = PullRequests(feed, github)
    source.refresh()

    feed.put(task("PROJ-7", "In Progress", references=[SECOND]))
    source.refresh()

    assert [pr["number"] for pr in _pulls(feed)["PROJ-7"]] == [1751]


def test_a_change_is_published_to_subscribers_and_an_unchanged_refresh_is_not() -> None:
    github = _Github(pr1750=_record(1750, "pending"))
    feed = _feed(proj_7=[FIRST])
    _, changes = feed.subscribe()
    source = PullRequests(feed, github)

    source.refresh()
    source.refresh()
    github.records[FIRST] = _record(1750, "pass")
    source.refresh()

    assert [changes.get_nowait() for _ in range(changes.qsize())] == [
        ("pulls", {"pulls": {"PROJ-7": [_record(1750, "pending")]}}),
        ("pulls", {"pulls": {"PROJ-7": [_record(1750, "pass")]}}),
    ]


class _Gh:
    """Stands in for `gh api graphql`: records the repository and numbers asked for and answers with `nodes`."""

    def __init__(self, nodes: dict[str, dict | None]) -> None:
        self.nodes = nodes
        self.asked: list[tuple[str, list[int]]] = []

    def __call__(self, repo: str, numbers: list[int]) -> dict:
        self.asked.append((repo, numbers))
        return self.nodes


@pytest.mark.parametrize(
    ("rollup", "checks"),
    [
        ("SUCCESS", "pass"),
        ("FAILURE", "failing"),
        ("ERROR", "failing"),
        ("PENDING", "pending"),
        ("EXPECTED", "pending"),
        (None, "none"),
        ("SOMETHING_NEW", "none"),
    ],
)
def test_the_head_commits_check_rollup_state_is_pass_failing_pending_or_none(rollup: str | None, checks: str) -> None:
    gh = _Gh({"p1750": _node(1750, rollup=rollup)})

    assert fetch([FIRST], gh)[FIRST]["checks"] == checks


def test_the_thread_count_is_the_unresolved_threads_only() -> None:
    gh = _Gh({"p1750": _node(1750, rollup="SUCCESS", threads=(True, False, False, False))})

    assert fetch([FIRST], gh)[FIRST]["threads"] == 3


def test_the_record_carries_the_number_url_and_merged_state() -> None:
    gh = _Gh({"p1750": _node(1750, rollup="SUCCESS", merged=True)})

    assert fetch([FIRST], gh)[FIRST] == _record(1750, "pass", merged=True)


def test_a_merged_prs_record_carries_the_merge_commit_sha_and_merge_time() -> None:
    gh = _Gh({"p1750": _node(1750, rollup="SUCCESS", merged=True, merge_commit=SHA, merged_at=MERGED_AT)})

    record = fetch([FIRST], gh)[FIRST]

    assert (record["merge_sha"], record["merged_at"]) == (SHA, MERGED_AT)


def test_an_open_prs_record_carries_no_merge_sha_or_merge_time() -> None:
    gh = _Gh({"p1750": _node(1750, rollup="SUCCESS")})

    record = fetch([FIRST], gh)[FIRST]

    assert (record["merge_sha"], record["merged_at"]) == (None, None)


def test_each_repository_is_asked_once_for_all_its_numbers() -> None:
    other = "https://github.com/other-org/tools/pull/9"
    gh = _Gh({"p1750": _node(1750, rollup=None), "p1751": _node(1751, rollup=None), "p9": _node(9, rollup=None)})

    fetch([FIRST, other, SECOND], gh)

    assert sorted(gh.asked) == [("acme/widgets", [1750, 1751]), ("other-org/tools", [9])]


def test_a_pr_github_does_not_return_is_left_out() -> None:
    gh = _Gh({"p1750": _node(1750, rollup=None), "p1751": None})

    assert list(fetch([FIRST, SECOND], gh)) == [FIRST]


def test_a_malformed_github_answer_is_a_failed_read_not_a_crash() -> None:
    gh = _Gh({"p1750": {"number": 1750, "merged": False}})

    with pytest.raises(GhUnavailableError, match="unexpected GraphQL answer for acme/widgets"):
        fetch([FIRST], gh)


OTHER = "https://github.com/other-org/tools/pull/9"


def _read_except(unreadable: set[str]):
    """A `read` that answers every repository but `unreadable`, which raise as an unreachable GitHub does."""

    def read(repo: str, numbers: list[int]) -> dict:
        if repo in unreadable:
            raise GhUnavailableError(f"{repo} is not readable")
        return {f"p{number}": _node(number, rollup="SUCCESS") for number in numbers}

    return read


def test_a_repository_that_cannot_be_read_does_not_hide_the_others_pull_requests() -> None:
    assert list(fetch([FIRST, OTHER], _read_except({"other-org/tools"}))) == [FIRST]


def test_every_readable_repository_contributes_its_pull_requests() -> None:
    assert set(fetch([FIRST, OTHER], _read_except(set()))) == {FIRST, OTHER}


def test_the_urls_of_a_repository_that_cannot_be_read_are_named_unread() -> None:
    assert fetch([FIRST, OTHER], _read_except({"other-org/tools"})).unread == {OTHER}


def test_a_partial_outage_keeps_the_unreadable_repositorys_last_value_stale_beside_the_fresh_ones() -> None:
    feed = _feed(proj_7=[FIRST], proj_9=[OTHER])
    github = _Github(pr1750=_record(1750, "pass"), pr9=_record(9, "pass"))
    github.records[OTHER] = {**_record(9, "pass"), "url": OTHER}
    source = PullRequests(feed, github)
    source.refresh()

    github.unread = {OTHER}
    github.records[FIRST] = _record(1750, "failing")
    source.refresh()

    assert _pulls(feed) == {
        "PROJ-7": [_record(1750, "failing")],
        "PROJ-9": [{**_record(9, "pass"), "url": OTHER, "stale": True}],
    }


def test_every_repository_failing_is_a_failed_read() -> None:
    with pytest.raises(GhUnavailableError, match="not readable"):
        fetch([FIRST, OTHER], _read_except({"acme/widgets", "other-org/tools"}))


def _run(monkeypatch: pytest.MonkeyPatch, *, stdout: str = "", stderr: str = "", code: int = 0) -> list[list[str]]:
    """Replace `subprocess.run` with a `gh` that answers as given; returns the commands it was asked to run."""
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs == {"capture_output": True, "text": True, "timeout": 30}
        return subprocess.CompletedProcess(command, code, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return commands


def test_one_gh_graphql_request_asks_for_every_number_in_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    commands = _run(monkeypatch, stdout='{"data": {"repository": {"p1": null}}}')

    assert read_repository("acme/widgets", [1, 2]) == {"p1": None}

    (command,) = commands
    assert command == [
        "gh",
        "api",
        "graphql",
        "-f",
        "query=query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) "
        "{ p1: pullRequest(number: 1) { ...Pull } p2: pullRequest(number: 2) { ...Pull } } }"
        "\nfragment Pull on PullRequest {\n  number\n  merged\n  mergedAt\n  mergeCommit { oid }\n"
        "  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }\n"
        "  reviewThreads(first: 100) { nodes { isResolved } }\n}\n",
        "-f",
        "owner=acme",
        "-f",
        "name=widgets",
    ]


def test_gh_exiting_non_zero_for_one_missing_pr_still_yields_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    _run(monkeypatch, stdout='{"data": {"repository": {"p1": {"number": 1}, "p2": null}}}', stderr="not found", code=1)

    assert read_repository("acme/widgets", [1, 2]) == {"p1": {"number": 1}, "p2": None}


@pytest.mark.parametrize(
    ("stdout", "stderr", "code", "message"),
    [
        ("", "gh: not logged in", 1, "gh: not logged in"),
        ("", "", 4, "gh exited 4"),
        ("not json", "", 0, "gh exited 0"),
        ('{"data": {"repository": null}}', "", 0, "acme/widgets is not readable"),
    ],
)
def test_gh_failures_are_a_failed_read_naming_why(
    monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, code: int, message: str
) -> None:
    _run(monkeypatch, stdout=stdout, stderr=stderr, code=code)

    with pytest.raises(GhUnavailableError, match=message):
        read_repository("acme/widgets", [1])


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FileNotFoundError("gh is not installed"), "gh is not installed"),
        (subprocess.TimeoutExpired("gh api", 30), "timed out after 30 seconds"),
    ],
)
def test_a_missing_or_hung_gh_is_a_failed_read_naming_why(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    def run(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(GhUnavailableError, match=message):
        read_repository("acme/widgets", [1])


class _Pins:
    """Stands in for the pin reads: the widgets merge pins POINTER, which contains the skills merge."""

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        return "pointer" if (repo, sha, path) == ("acme/widgets", SHA, "skills") else None

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        return (repo, sha, pointer) == ("acme/skills", "5" * 40, "pointer")


def test_a_merged_pr_of_a_pinned_repository_carries_the_parent_merge_that_applies_it() -> None:
    child = "https://github.com/acme/skills/pull/7"
    github = _Github(pr1750=_record(1750, "pass", merged=True, merge_sha=SHA, merged_at=MERGED_AT))
    github.records[child] = {
        **_record(7, "pass", merged=True, merge_sha="5" * 40, merged_at="2026-10-06T20:00:00Z"),
        "url": child,
    }
    feed = _feed(proj_7=[FIRST], proj_8=[child])
    repos = (Repo(name="skills", path="skills", applied_by="pin-bump"),)

    PullRequests(feed, github, repos=repos, pins=_Pins()).refresh()

    assert _pulls(feed)["PROJ-8"][0]["applied_by"] == SHA
    assert "applied_by" not in _pulls(feed)["PROJ-7"][0]


def _pinned_github() -> tuple[_Github, str]:
    child = "https://github.com/acme/skills/pull/7"
    github = _Github(pr1750=_record(1750, "pass", merged=True, merge_sha=SHA, merged_at=MERGED_AT))
    github.records[child] = {
        **_record(7, "pass", merged=True, merge_sha="5" * 40, merged_at="2026-10-06T20:00:00Z"),
        "url": child,
    }
    return github, child


def _gh_pins(asked: list[str]):
    """`gh api` answering the widgets merge's pointer and a compare that contains the skills merge, noting each call."""

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        asked.append(command[2])
        answer = "pointer" if "/contents/" in command[2] else "ahead"
        return subprocess.CompletedProcess(command, 0, answer, "")

    return run


def test_pin_answers_saved_with_the_board_spare_a_restarted_reader_every_pointer_and_compare_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(subprocess, "run", _gh_pins(asked))
    repos = (Repo(name="skills", path="skills", applied_by="pin-bump"),)
    github, child = _pinned_github()
    before = _feed(proj_7=[FIRST], proj_8=[child])
    PullRequests(before, github, repos=repos, pins=GitHub()).refresh()
    assert len(asked) == 2

    after = _feed(proj_7=[FIRST], proj_8=[child])
    after.set_pulls({}, before.pull_answers())  # what `BoardFeed.resume` restores
    asked.clear()
    restarted = PullRequests(after, github, repos=repos, pins=GitHub())
    restarted.restore()
    restarted.refresh()

    assert asked == []
    assert _pulls(after)["PROJ-8"][0]["applied_by"] == SHA


def test_the_first_refresh_waits_for_the_board_replay_and_then_runs_without_waiting_the_interval() -> None:
    feed = _feed(proj_7=[FIRST])
    feed.await_stream()
    asked = threading.Event()
    github = _Github(pr1750=_record(1750, "pass"))

    def read(urls: Collection[str]) -> Pulls:
        asked.set()
        return github(urls)

    source = PullRequests(feed, read)
    threading.Thread(target=source.run_forever, kwargs={"interval_s": 3600}, daemon=True).start()

    assert not asked.wait(0.2)
    feed.expect("0-0")
    assert asked.wait(5)
