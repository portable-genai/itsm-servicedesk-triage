"""The triage service: run the deterministic engine, redact, audit, return the worksheet.

The consequential decision (the category, the priority, the queue, whether to escalate) is the
pure :class:`~.triage_engine.TriageEngine`; this layer adds the side effects the engine must not
have. It redacts before the audit write (a raw identifier never reaches the WORM record), it
records an already-redacted event, and it returns the engine's result unchanged so the API, the
CLI and the agent all see the same worksheet. Rule R8 routing is the SURFACE's job (each surface
routes in the same call that produced the result); the service does not swallow it.

The engine is injected, so a test and the eval oracle drive the exact object the service runs.
"""

from __future__ import annotations

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.observability import ObservabilityTracerPort
from .kernel import AuditEvent, utcnow
from .models import TriageInput, TriageResult
from .pii import PII_PATTERNS, redacted_citations
from .triage_engine import TriageEngine

#: One span per triaged ticket. Structural attributes only: see :meth:`TriageService.triage`.
_TRIAGE_SPAN = "itsm.triage"


class TriageService:
    """Route a ticket deterministically and record an already-redacted audit event."""

    def __init__(
        self,
        audit: AuditSinkPort,
        engine: TriageEngine,
        *,
        tracer: ObservabilityTracerPort,
    ) -> None:
        self._audit = audit
        self._engine = engine
        self._tracer = tracer

    def triage(self, ticket: TriageInput, *, actor: str) -> TriageResult:
        """Triage ``ticket`` deterministically and record the already-redacted audit event.

        The whole path runs inside one span. Its attributes are STRUCTURAL only, never the
        ticket text, the subject or the resulting queue: a trace backend is not the WORM
        audit trail; it has no redaction stage, a wider read audience and no retention rule
        written against a regulator's requirement, so anything content-shaped that reaches a
        span has left the boundary the ``redact`` call below exists to hold, and left it
        silently.
        """
        with self._tracer.span(_TRIAGE_SPAN, action="triage", actor=actor):
            return self._triage(ticket, actor=actor)

    def _triage(self, ticket: TriageInput, *, actor: str) -> TriageResult:
        result = self._engine.triage(ticket)

        # Redact BEFORE the audit write, on EVERY content field the event carries and not just
        # the summary. Masking the summary and then passing `result.citations` straight through
        # is how the raw ticket body stayed in the WORM record: the evidence citation quotes the
        # body verbatim and its locator is built from the subject line, so the record kept
        # exactly what the line above had removed, in a store nothing can correct later.
        detail = f"{result.summary} :: {ticket.text}"
        self._audit.record(
            AuditEvent(
                action="triage",
                actor=actor,
                decision=result.decision,
                severity=result.severity,
                redacted_summary=redact(detail, PII_PATTERNS),
                citations=redacted_citations(result.citations),
                timestamp=utcnow(),
            )
        )
        return result
