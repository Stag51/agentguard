"""Instrumentation SDK: wrap agent steps so they emit OpenTelemetry spans.

Usage inside any agent (LangGraph or plain Python):

    from agentguard.sdk import span

    with span("tool", "lookup_order", input={"order_id": "ORD-1"}) as s:
        result = lookup_order("ORD-1")
        s.set_output(result)

    with span("llm", "claude-sonnet") as s:
        reply = call_model(...)
        s.set_usage(tokens_in=120, tokens_out=40, cost_usd=0.0007)

The runner sets the "trace context" (run id, case id, repeat) with
`trace_context(...)`; every span created inside it is tagged with those ids so
the collector can attach it to the right attempt. Outside a context, `span` is a
no-op wrapper, so instrumented agents run normally in production.

WHY a context manager and not only a decorator: LLM and tool calls need to record
usage and outputs *after* they finish, which a `with` block handles cleanly.

Failure policy (N4): SDK errors are swallowed and logged. Exceptions raised by
the agent's own code are recorded on the span and re-raised unchanged.

Does NOT export anywhere by itself; see agentguard.collector.exporter.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from ..collector.exporter import DBSpanExporter
from ..redact import redact

log = logging.getLogger("agentguard.sdk")


@dataclass(frozen=True)
class TraceContext:
    run_id: str
    case_id: str
    repeat: int = 0


_CTX: ContextVar[TraceContext | None] = ContextVar("agentguard_ctx", default=None)
_tracer = None


def get_context() -> TraceContext | None:
    """Current run/case/repeat, or None outside an evaluation."""
    return _CTX.get()


@contextmanager
def trace_context(run_id: str, case_id: str, repeat: int = 0) -> Iterator[TraceContext]:
    """Tag every span created inside this block with the given ids."""
    ctx = TraceContext(run_id, case_id, repeat)
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def _get_tracer():
    """Create the tracer lazily.

    WHY a private TracerProvider (not the global one): the global provider can be
    set only once per process, which breaks tests and host apps that already
    configure OpenTelemetry.
    WHY SimpleSpanProcessor: spans are written when they end, so the scorer can
    read them right after the attempt. A batching processor would be faster but
    needs an explicit flush; see docs/failure-modes.md.
    """
    global _tracer
    if _tracer is None:
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(DBSpanExporter()))
        _tracer = provider.get_tracer("agentguard")
    return _tracer


def _dump(value: Any) -> str:
    """JSON-encode and redact a value for storage."""
    try:
        return redact(json.dumps(value, default=str, ensure_ascii=False))
    except Exception:
        return redact(str(value))


class SpanHandle:
    """Collects data about a span while the `with` block runs."""

    def __init__(self) -> None:
        self.output: Any = None
        self.has_output = False
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.error: str | None = None

    def set_output(self, value: Any) -> None:
        self.output, self.has_output = value, True

    def set_usage(self, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0) -> None:
        self.tokens_in, self.tokens_out, self.cost_usd = tokens_in, tokens_out, cost_usd

    def set_error(self, message: str) -> None:
        """Record a failure that the agent handled itself (no exception raised)."""
        self.error = message


@contextmanager
def span(kind: str, name: str, input: Any = None) -> Iterator[SpanHandle]:
    """Record one step. `kind` is "llm", "tool" or "retrieval"."""
    handle = SpanHandle()
    ctx = _CTX.get()
    otel_cm = None
    otel_span = None
    if ctx is not None:
        try:
            otel_cm = _get_tracer().start_as_current_span(
                f"{kind}:{name}", record_exception=False, set_status_on_exception=False
            )
            otel_span = otel_cm.__enter__()
        except Exception:
            log.warning("could not start span", exc_info=True)
            otel_cm = otel_span = None
    try:
        yield handle
    except BaseException as exc:
        handle.error = f"{type(exc).__name__}: {exc}"
        raise  # WHY: the agent's own errors are never hidden by tracing
    finally:
        if otel_span is not None and ctx is not None:
            try:
                otel_span.set_attribute("ag.run_id", ctx.run_id)
                otel_span.set_attribute("ag.case_id", ctx.case_id)
                otel_span.set_attribute("ag.repeat", ctx.repeat)
                otel_span.set_attribute("ag.type", kind)
                otel_span.set_attribute("ag.name", name)
                if input is not None:
                    otel_span.set_attribute("ag.input", _dump(input))
                if handle.has_output:
                    otel_span.set_attribute("ag.output", _dump(handle.output))
                otel_span.set_attribute("ag.tokens_in", handle.tokens_in)
                otel_span.set_attribute("ag.tokens_out", handle.tokens_out)
                otel_span.set_attribute("ag.cost_usd", handle.cost_usd)
                if handle.error:
                    otel_span.set_attribute("ag.error", redact(handle.error))
                otel_cm.__exit__(None, None, None)  # type: ignore[union-attr]
            except Exception:
                log.warning("could not finish span", exc_info=True)
