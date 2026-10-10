"""GET /api/analytics/missed-loads and /api/analytics/trace-clusters over OTLP exports published to the event log."""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.config.analytics import Analytics, SkillLoad
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.telemetry import TelemetryLog, signals
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse.contracts.adapters import BoardTask, TaskKeys
from starpulse.tests.machines import MACHINES

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()
ANALYTICS = Analytics(
    roots=("/r", "/r/.claude/worktrees/*"),
    lifecycle_skills=frozenset({"starting-tasks"}),
    skill_loads=(
        SkillLoad("operating-unraid", activities=frozenset({"ssh *@unraid"})),
        SkillLoad("verifying-claims", title=re.compile("^verify", re.IGNORECASE), label="validation"),
    ),
)
DELIVERY = [("Bash", {"command": "git status && gh pr view 3"}), ("Read", {"file_path": "/r/README.md"})]


def _attributes(**values: object) -> list[dict]:
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in values.items()]


def export(n: int, work: list[tuple[str, dict[str, Any]]], skills: tuple[str, ...] = ()) -> dict:
    """One headless Claude Code session that worked TASK-`n`: a prompt, the delivery every task does, then `work`."""
    records, at = [], NOW - 3600 + n
    events = [("user_prompt", {})]
    events += [("tool_result", {"tool_name": t, "tool_input": json.dumps(i), "success": "true"}) for t, i in DELIVERY + work]
    events += [("skill_activated", {"skill.name": s}) for s in skills]
    for sequence, (name, attributes) in enumerate(events):
        stamp = datetime.fromtimestamp(at + sequence, UTC).isoformat().replace("+00:00", "Z")
        records.append(
            {
                "attributes": _attributes(
                    **{"session.id": f"s{n}", "event.name": name, "event.timestamp": stamp, "event.sequence": sequence},
                    **attributes,
                )
            }
        )
    resource = {"attributes": _attributes(**{"vcs.ref.head.name": f"claude/task-{n}-x"})}
    return {"resourceLogs": [{"resource": resource, "scopeLogs": [{"logRecords": records}]}]}


def corpus() -> list[dict]:
    """Sixty sessions: six that queried and one that loaded a skill, six that reached unraid, and the rest delivery."""
    obs = [
        export(n, [("Bash", {"command": "bin/obs.py query up | head"}), ("Bash", {"command": "psql -c 'select 1'"})],
               ("querying-observability",) if n == 0 else ())
        for n in range(6)
    ]
    unraid = [
        export(n, [("Bash", {"command": "ssh root@unraid 'docker ps'"})], ("operating-unraid",) if n == 6 else ())
        for n in range(6, 12)
    ]
    return [*obs, *unraid, *(export(n, [], ("starting-tasks",)) for n in range(12, 60))]


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, path), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    for payload in corpus():
        telemetry.publish(signals(payload))
    feed = BoardFeed(machines=MACHINES, keys=KEYS)
    feed.put(BoardTask(id="TASK-20", team="demo", title="Verify the thing", lane="done", labels=[], settled="completed"))
    feed.put(BoardTask(id="TASK-21", team="demo", title="Check nothing", lane="done", labels=["validation"], settled="completed"))
    with serve(tmp_path, feed, telemetry=telemetry, clock=lambda: NOW, analytics=ANALYTICS) as server:
        yield server


def test_a_skills_trigger_run_without_loading_it_is_a_missed_load(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "/api/analytics/missed-loads?hours=24")

    assert status == 200
    skills = {s["skill"]: s for s in body["skills"]}
    assert (skills["operating-unraid"]["performed"], skills["operating-unraid"]["missed"]) == (6, 5)
    assert {c["task"] for c in skills["operating-unraid"]["listed"]} == {f"TASK-{n}" for n in range(7, 12)}
    # a title or a label names a task shape; both settled tasks were worked, and neither loaded the skill
    assert (skills["verifying-claims"]["performed"], skills["verifying-claims"]["missed"]) == (2, 2)
    assert (body["now"], body["window_s"]) == (NOW, 24 * 3600)


def test_missed_loads_can_be_narrowed_to_a_skill_and_a_list_length(server: ThreadingHTTPServer) -> None:
    _, body = _get(server, "/api/analytics/missed-loads?skill=operating-unraid&list=2")

    (found,) = body["skills"]
    assert (found["skill"], found["missed"], len(found["listed"])) == ("operating-unraid", 5, 2)


def test_recurring_work_is_a_trace_cluster_with_its_skills_and_what_it_missed(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "/api/analytics/trace-clusters?hours=24&min_sessions=5")

    assert status == 200
    assert (body["cases"], body["clustered"]) == (60, 12)
    obs, unraid = body["clusters"]
    assert (obs["descriptors"], obs["sessions"], obs["cases"]) == (["a:bin/obs.py", "a:psql"], 6, 6)
    assert obs["skills"] == [{"skill": "querying-observability", "cases": 1}]
    assert (obs["uncovered"], obs["tasks"][:2]) == (5, ["TASK-0", "TASK-1"])
    assert (unraid["descriptors"], unraid["sessions"]) == (["a:ssh root@unraid"], 6)
    assert unraid["missed_loads"] == [{"skill": "operating-unraid", "performed": 6, "missed": 5}]
    assert obs["medoid"] is None and unraid["outliers"] == []


def test_outliers_name_the_medoid_and_each_cases_edits_from_it(server: ThreadingHTTPServer) -> None:
    _, body = _get(server, "/api/analytics/trace-clusters?outliers=2")

    unraid = body["clusters"][1]
    assert unraid["medoid"]["trace"] == ["git status", "gh pr view", "Read", "ssh root@unraid"]
    assert [o["distance"] for o in unraid["outliers"]] == [0.0, 0.0]


def test_min_sessions_leaves_out_the_smaller_clusters(server: ThreadingHTTPServer) -> None:
    _, body = _get(server, "/api/analytics/trace-clusters?min_sessions=7")

    assert body["clusters"] == []


@pytest.mark.parametrize(
    "query",
    ["hours=0", "hours=soon", "threshold=0", "threshold=2.5", "min_sessions=0", "outliers=-1", "outliers=x", "new_hours=0"],
)
def test_a_number_out_of_range_is_refused(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _get(server, f"/api/analytics/trace-clusters?{query}")

    assert (status, "error" in body) == (400, True)


@pytest.mark.parametrize("path", ["/api/analytics/missed-loads", "/api/analytics/trace-clusters"])
def test_an_instance_that_receives_no_telemetry_cannot_report_them(tmp_path: Path, path: str) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES, keys=KEYS)) as server:
        status, body = _get(server, path)

    assert (status, "telemetry" in body["error"]) == (501, True)
