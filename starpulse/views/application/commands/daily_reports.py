"""The daily report of a machine: counts and summed durations by day, month, year or range."""

from typing import Any

from starpulse.contracts.api.dto.requests import DailyReportListRequest
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.application.commands.guard import with_request


@with_request(DailyReportListRequest, "Reading a daily report")
def daily_reports_list(request: DailyReportListRequest, history: HistoryStore) -> tuple[int, dict[str, Any]]:
    """The buckets of the `machine`'s daily rows from `since` to `until`, `limit` from `offset`: the HTTP status and
    JSON body. A range with no move is an empty list; a missing `machine`, `since` or `until` and a `since` after
    `until` are 422."""
    filters = request.filter
    if not (filters.machine and filters.since and filters.until):
        return 422, {"error": "name the machine and the range: filter.machine, filter.since and filter.until"}
    if filters.since > filters.until:
        return 422, {"error": f"filter.since {filters.since} is after filter.until {filters.until}"}
    items = history.daily_report(
        filters.machine, filters.since.isoformat(), filters.until.isoformat(), state=filters.state, bucket=filters.bucket
    )
    return 200, {"items": items[request.offset : request.offset + request.limit]}
