"""`GET /api/views/{id}`: the one GraphQL document a view stores in `starpulse.toml`, which its page sends to `/graphql`."""

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute
from starpulse.views.model.encoding import encode


async def view(request: Request) -> Response:
    name = request.path_params["id"]
    query = seams(request).services.views.get(name)
    if query is None:
        return answer(request, encode("error", {"error": f"no view named {name}"}), 404)
    return answer(request, encode("view", {"name": name, "query": query}))


routes: list[ApiRoute] = [ReadRoute("/views/{id}", view)]
