"""OpenTelemetry span exporter that writes spans to the database as Steps.

Role in the architecture: this is the "collector". The SDK emits standard OTel
spans; this exporter turns them into rows.

WHY a custom exporter (not an OTLP collector process): keeps the project
runnable with one command. Because it speaks the standard SpanExporter
interface, swapping in an OTLP exporter later needs no SDK change.

Failure policy (N4): this must NEVER raise into the agent. Errors are logged and
the span is dropped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from .. import db
from .payloads import write_payload

log = logging.getLogger("agentguard.collector")


class DBSpanExporter(SpanExporter):
    def export(self, spans) -> SpanExportResult:  # type: ignore[override]
        try:
            with db.get_session() as session:
                for span in spans:
                    step = self._to_step(span, session)
                    if step is not None:
                        session.add(step)
                session.commit()
        except Exception:  # WHY: observability must never take the agent down
            log.warning("failed to export spans; dropping them", exc_info=True)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    @staticmethod
    def _to_step(span: ReadableSpan, session) -> db.Step | None:
        a = span.attributes or {}
        if "ag.run_id" not in a:
            return None  # not one of ours (e.g. a library's own span)
        return db.Step(
            run_id=str(a["ag.run_id"]),
            case_id=str(a["ag.case_id"]),
            repeat=int(a.get("ag.repeat", 0)),
            type=str(a.get("ag.type", "tool")),
            name=str(a.get("ag.name", span.name)),
            input_ref=write_payload(str(a["ag.input"]), session) if "ag.input" in a else None,
            output_ref=write_payload(str(a["ag.output"]), session) if "ag.output" in a else None,
            latency_ms=((span.end_time or 0) - (span.start_time or 0)) / 1e6,
            tokens_in=int(a.get("ag.tokens_in", 0)),
            tokens_out=int(a.get("ag.tokens_out", 0)),
            cost_usd=float(a.get("ag.cost_usd", 0.0)),
            error=str(a["ag.error"]) if "ag.error" in a else None,
            started_at=datetime.fromtimestamp((span.start_time or 0) / 1e9, tz=timezone.utc),
        )
