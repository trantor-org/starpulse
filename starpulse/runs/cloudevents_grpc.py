"""The CloudEvents ingest over gRPC: `starpulse.v1.CloudEventsIngest`, `Publish` and `PublishBatch`.

The same ingest as `POST /api/machine-events`, bound to the CloudEvents protobuf format (`io.cloudevents.v1`) and served
by a Connect-style ASGI handler on the page's port, so `grpc-status` travels in HTTP/2 trailers. The producer's token is
the `authorization` metadata (`Bearer <token>`); the checks and the append are `CloudEventsIngest.write`'s, so an HTTP
status it answers is the gRPC code of the same refusal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.method import IdempotencyLevel, MethodInfo
from connectrpc.server import ConnectASGIApplication, Endpoint
from google.protobuf.empty_pb2 import Empty

from starpulse._internal.config.config import MAX_BATCH
from starpulse.runs.wire.cloudevents_pb2 import CloudEvent, CloudEventBatch

if TYPE_CHECKING:
    from connectrpc.request import RequestContext

    from starpulse.runs.cloudevents import CloudEventsIngest

SERVICE = "starpulse.v1.CloudEventsIngest"
#: The URL prefix every method of the service is served under.
PATH = f"/{SERVICE}/"
_CODES = {
    400: Code.INVALID_ARGUMENT,
    401: Code.UNAUTHENTICATED,
    403: Code.PERMISSION_DENIED,
    413: Code.RESOURCE_EXHAUSTED,
    503: Code.UNAVAILABLE,
}


def _attribute(value: Any) -> Any:
    kind = value.WhichOneof("attr")
    if kind == "ce_timestamp":
        return value.ce_timestamp.ToDatetime(tzinfo=UTC).isoformat()
    return None if kind is None else getattr(value, kind)


def _json(event: CloudEvent) -> dict[str, Any]:
    """The structured-JSON form of `event`, which the ingest checks as it does an HTTP body."""
    fields: dict[str, Any] = {
        "specversion": event.spec_version,
        "id": event.id,
        "source": event.source,
        "type": event.type,
    }
    fields |= {name: _attribute(value) for name, value in event.attributes.items()}
    carried = event.WhichOneof("data")
    if carried == "proto_data":
        raise ConnectError(Code.INVALID_ARGUMENT, "data is JSON text or bytes, not a protobuf Any")
    if carried is not None:
        try:
            fields["data"] = json.loads(getattr(event, carried))
        except ValueError as bad:
            raise ConnectError(Code.INVALID_ARGUMENT, "data is not JSON") from bad
    return fields


class _Ingest:
    def __init__(self, ingest: CloudEventsIngest) -> None:
        self._ingest = ingest

    async def publish(self, request: CloudEvent, ctx: RequestContext[CloudEvent, Empty]) -> Empty:
        return await self._write(ctx, [request])

    async def publish_batch(self, request: CloudEventBatch, ctx: RequestContext[CloudEventBatch, Empty]) -> Empty:
        if not 0 < len(request.events) <= MAX_BATCH:
            raise ConnectError(Code.INVALID_ARGUMENT, f"a batch is 1 to {MAX_BATCH} events")
        return await self._write(ctx, list(request.events))

    async def _write(self, ctx: RequestContext[Any, Empty], events: list[CloudEvent]) -> Empty:
        name = self._ingest.owner(ctx.request_headers().get("authorization"))
        if name is None:
            raise ConnectError(
                Code.UNAUTHENTICATED, "a valid producer token is required: authorization: Bearer <token>"
            )
        sent = [_json(event) for event in events]
        status, body = await to_thread.run_sync(self._ingest.write, name, sent)
        if status != 201:
            raise ConnectError(_CODES.get(status, Code.UNKNOWN), body.get("error", "refused"))
        return Empty()


def _endpoints(service: _Ingest) -> Mapping[str, Endpoint]:
    def method(name: str, request: type, function: Any) -> tuple[str, Endpoint]:
        info = MethodInfo(
            name=name,
            service_name=SERVICE,
            input=request,
            output=Empty,
            idempotency_level=IdempotencyLevel.UNKNOWN,
        )
        return f"{PATH}{name}", Endpoint.unary(info, function)

    return dict(
        [
            method("Publish", CloudEvent, service.publish),
            method("PublishBatch", CloudEventBatch, service.publish_batch),
        ]
    )


class _App(ConnectASGIApplication[_Ingest]):
    @property
    def path(self) -> str:
        return PATH


def cloudevents_grpc(ingest: CloudEventsIngest) -> ConnectASGIApplication[_Ingest]:
    """The ASGI app that serves `ingest` over gRPC and Connect; it answers only a path under `PATH`."""
    return _App(service=_Ingest(ingest), endpoints=_endpoints)
