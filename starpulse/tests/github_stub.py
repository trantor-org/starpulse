"""A GitHub REST API answering from responses recorded off `trantor-org/starpulse`, for the Actions adapter's tests.

`recorded` is the `Transport` the adapter takes: it serves the repository's workflows, each workflow's latest run, that
run's jobs and each workflow file, and records every call it gets. The recorded runs are one queued, one queued and one
cancelled; a test that wants a run with steps names `ci-success` for the CI workflow.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

REPO = "trantor-org/starpulse"
FIXTURES = Path(__file__).parent / "fixtures" / "github_actions"
#: The workflow ids as recorded, by the file each one is.
WORKFLOW_IDS = {"ci": 374416380, "release": 374969302, "ui-preview": 375863838}

Answer = tuple[int, dict]


class Recorded:
    """The transport, and the `(method, path, body)` of every call it was given."""

    def __init__(
        self,
        runs: Mapping[str, str] | None = None,
        dispatch: Callable[[dict | None], Answer] | None = None,
        *,
        overrides: Mapping[str, Answer] | None = None,
    ) -> None:
        """`runs` names the fixture each workflow's latest run is read from (`{"ci": "ci-success"}`), `dispatch`
        answers a dispatch with the body it got, and `overrides` replaces the answer to a path."""
        self.calls: list[tuple[str, str, dict | None]] = []
        self._dispatch = dispatch or (lambda body: (204, {}))
        self._overrides = dict(overrides or {})
        self._served: dict[str, Answer] = {f"/repos/{REPO}/actions/workflows?per_page=100": (200, self._read("workflows"))}
        self._served[f"/repos/{REPO}"] = (200, {"default_branch": "main"})
        for workflow, workflow_id in WORKFLOW_IDS.items():
            recorded = (runs or {}).get(workflow, workflow)
            run = self._read(f"{recorded}-runs")
            self._served[f"/repos/{REPO}/actions/workflows/{workflow_id}/runs?per_page=1"] = (200, run)
            for one in run["workflow_runs"]:
                self._served[f"/repos/{REPO}/actions/runs/{one['id']}/jobs?per_page=100"] = (200, self._read(f"{recorded}-jobs"))
            self._served[f"/repos/{REPO}/contents/.github/workflows/{workflow}.yml"] = (
                200,
                self._read(f"{workflow}-contents"),
            )

    @staticmethod
    def _read(name: str) -> dict:
        return json.loads((FIXTURES / f"{name}.json").read_text())

    def __call__(self, method: str, path: str, body: dict | None) -> Answer:
        self.calls.append((method, path, body))
        if method == "POST" and path.endswith("/dispatches"):
            return self._dispatch(body)
        return self._overrides.get(path) or self._served.get(path, (404, {}))

    def paths(self, method: str = "GET") -> list[str]:
        return [path for verb, path, _ in self.calls if verb == method]
