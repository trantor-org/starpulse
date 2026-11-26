"""Spans for the API's requests: `configure` exports them over OTLP when the standard `OTEL_*` environment names an
endpoint, and until then every span is a no-op."""

from collections.abc import Mapping
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import Engine, event

_ENDPOINTS = ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
_STATEMENT_CHARS = 500


def configure(environ: Mapping[str, str]) -> None:
    """Export spans to the OTLP endpoint `environ` names; without one, export none."""
    if any(environ.get(name) for name in _ENDPOINTS):
        install(BatchSpanProcessor(OTLPSpanExporter()))


def install(processor: SpanProcessor) -> None:
    """Hand every span, and each SQL statement run under a request's span, to `processor`."""
    provider = TracerProvider()  # its resource reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    event.listen(Engine, "before_cursor_execute", _began)
    event.listen(Engine, "after_cursor_execute", _ended)
    event.listen(Engine, "handle_error", _failed)


def _began(connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
    if trace.get_current_span().is_recording():  # a statement outside a request is no span of its own
        context.sql_span = trace.get_tracer("starpulse").start_span(
            "sql", attributes={"db.statement": statement[:_STATEMENT_CHARS]}
        )


def _ended(connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
    if span := getattr(context, "sql_span", None):
        span.end()


def _failed(exception_context: Any) -> None:
    if span := getattr(exception_context.execution_context, "sql_span", None):
        span.set_status(Status(StatusCode.ERROR, str(exception_context.original_exception)))
        span.end()
