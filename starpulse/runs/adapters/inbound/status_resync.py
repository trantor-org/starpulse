"""A commit status Woodpecker posts asks its runs instance to list its pipelines again, so the page follows a pipeline
without polling the server (`runs:resync`, read by `follow_resync`); the runtime root hands it to the `github-events` consumer."""

from collections.abc import Mapping

from starpulse.event_log.event_log import EventLog
from starpulse.github.model.checks import report_of
from starpulse.runs.model.run_events import RESYNC

#: The context prefix of the statuses Woodpecker posts (`Validate (python)`); a status of another publisher has none.
CONTEXT = "Validate ("


class Resync:
    """Publishes a `runs:resync` for the instance of the repository a Woodpecker `status` delivery names; `instances` is each
    repository's instance name."""

    def __init__(self, log: EventLog, instances: Mapping[str, str]) -> None:
        self.log, self.instances = log, instances

    def __call__(self, event: str, body: bytes) -> None:
        report = report_of(event, body) if event == "status" else None
        if report is not None and report.name.startswith(CONTEXT) and (instance := self.instances.get(report.repository)):
            self.log.publish(RESYNC, {"instance": instance})
