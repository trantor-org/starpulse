"""`ci-event.yml` only submits GitHub's pull_request and merge_group events to trantor's `ci-sp-*` Dagu DAGs.

These read the tracked workflow rather than running it: the claim is that the job holds no PR code, no secret and no
runner past the submit, and a stubbed run would prove the stub.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci-event.yml"
DAGS = ["ci-sp-python", "ci-sp-web", "ci-sp-contract", "ci-sp-static"]


def workflow() -> dict:
    document = yaml.safe_load(WORKFLOW.read_text())
    document["on"] = document.pop(True)  # PyYAML reads the bare `on` key as boolean True
    return document


def steps() -> list[dict]:
    return [step for job in workflow()["jobs"].values() for step in job["steps"]]


def run_text() -> str:
    return "\n".join(step.get("run", "") for step in steps())


def test_it_takes_pull_request_and_merge_group_events_only():
    assert set(workflow()["on"]) == {"pull_request", "merge_group"}


def test_it_submits_each_of_the_four_dags_without_observing_them():
    run = run_text()

    assert "for dag in " + " ".join(DAGS) + "; do" in run
    assert '--dag "$dag"' in run
    assert "bin/dagu_event.py submit" in run
    assert "--no-observe" in run


def test_it_names_the_event_and_the_queue_ref():
    run = run_text()

    assert '--event-name "$EVENT_NAME"' in run
    assert '--merge-queue-ref "$MERGE_QUEUE_REF"' in run


def test_it_checks_out_no_pull_request_code():
    assert [step for step in steps() if "uses" in step] == []
    assert "git " not in run_text()


def test_it_holds_no_secret_and_reads_the_repository_only():
    assert "secrets." not in WORKFLOW.read_text()
    assert workflow()["permissions"] == {"contents": "read"}


def test_it_is_one_short_job_with_the_submit_as_its_only_step():
    (job,) = workflow()["jobs"].values()

    assert job["runs-on"] == ["self-hosted", "ai-vm-1"]
    assert job["timeout-minutes"] <= 5
    assert len(job["steps"]) == 1


def test_a_rerun_needs_no_cancellation():
    assert "concurrency" not in workflow()
