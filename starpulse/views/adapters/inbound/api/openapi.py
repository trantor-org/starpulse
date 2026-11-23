"""`GET /api/openapi`: the OpenAPI document of every route; `GET /swagger` draws it as a Swagger page."""

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from starpulse.contracts.api.openapi import render
from starpulse.views.adapters.inbound.api.answering import answer, reading
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute

_SWAGGER = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.35.1"

#: The page holds nothing but the viewer's pinned scripts, which the browser checks against their hashes.
PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>StarPulse API</title>
<link rel="stylesheet" href="{_SWAGGER}/swagger-ui.css" integrity="sha384-WlYgdmXYOOBWL5apwjDEZwN+U3HmXSSu5R6V5aGxEcf7z+KuRNwBhoxKVN1i3D5I" crossorigin="anonymous">
</head>
<body>
<div id="swagger-ui"></div>
<script src="{_SWAGGER}/swagger-ui-bundle.js" integrity="sha384-J5eKRXKO1KzUTPkO0GRmGH2WEYUg6SSZlufilxvTwI6nmhLumjNWFMby3QQnyobZ" crossorigin="anonymous"></script>
<script>SwaggerUIBundle({{url: "/api/openapi", dom_id: "#swagger-ui"}});</script>
</body>
</html>
"""


@reading
def openapi(request: Request) -> Response:
    return answer(request, render().encode())


async def swagger(request: Request) -> Response:
    return HTMLResponse(PAGE)


routes: list[ApiRoute] = [ReadRoute("/openapi", openapi)]
