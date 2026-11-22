"""The per-task analytics the page reads: `GET /api/task-spend/{id}`, `/api/task-diff/{id}` and `/api/task-cost-to-go/{id}`.

One task's spend, or its kind and size's diff and cost-to-go rows, read from the stored fold rows.
"""

from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, Endpoint, ReadRoute
from starpulse.views.application.queries.responses import (
    cost_to_go_response,
    diff_response,
    refuses_at_once,
    spend_response,
    task_cost_to_go_response,
    task_diff_response,
    task_spend_response,
)
from starpulse.views.ports.services import Services

_Respond = Callable[..., tuple[bytes, int]]


def _kept(
    request: Request,
    services: Services,
    asked: dict[str, list[str]],
    compute: Callable[[], tuple[bytes, int]],
    now: Callable[[], float],
    path: str,
) -> tuple[bytes, int]:
    """`compute`'s answer, or the kept answer to this query, kept under `path` when the
    deployment keeps them (`Answers`); a query that only refuses (`refuses_at_once`, the window `hours`)
    never waits behind a fold."""
    if services.answers is None:
        return compute()
    return services.answers.answer(
        path,
        str(sorted(request.query_params.multi_items())),
        compute,
        lambda: refuses_at_once(services.telemetry, asked, now()),
    )


def _per_task(week_of: _Respond, week_path: str, respond: _Respond) -> Endpoint:
    """A task's read of the window answer at `week_path` that `week_of` computes, the one every task and the
    board-wide read share, so opening a task folds nothing of its own."""

    @reading
    def endpoint(request: Request) -> Response:
        api = seams(request)
        services = api.services
        feed = api.feed
        asked = query(request)
        week = _kept(
            request,
            services,
            asked,
            lambda: week_of(services.telemetry, asked, feed.keys, feed.titled, api.clock(), services.analytics),
            api.clock,
            path=week_path,
        )
        task = request.path_params["id"]
        return answer(request, *respond(week, task, feed.titled))

    return endpoint


routes: list[ApiRoute] = [
    ReadRoute(
        "/task-spend/{id:path}",
        _per_task(spend_response, "spend", lambda week, task, _: task_spend_response(week, task)),
        params=frozenset({"hours"}),
    ),
    ReadRoute("/task-diff/{id:path}", _per_task(diff_response, "diff", task_diff_response), params=frozenset({"hours"})),
    ReadRoute(
        "/task-cost-to-go/{id:path}",
        _per_task(cost_to_go_response, "cost-to-go", task_cost_to_go_response),
        params=frozenset({"hours"}),
    ),
]
