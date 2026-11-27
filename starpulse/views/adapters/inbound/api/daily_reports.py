"""Daily reports.

- `POST /api/daily-reports`: one machine's counts and summed durations of its moves over a range of local days, summed
  per day, month, year or the range from the stored daily rows (422 for a missing machine or range, or a range backwards).
"""

from typing import TYPE_CHECKING

from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole_body
from starpulse.views.application.commands.daily_reports import daily_reports_list

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    history = api.history
    return [
        WriteRoute(
            "/daily-reports",
            ("POST",),
            guarded("daily_reports", whole_body(lambda client, raw: daily_reports_list(client, raw, history))),
        ),
    ]
