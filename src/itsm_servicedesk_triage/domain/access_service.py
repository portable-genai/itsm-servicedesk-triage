"""The access service: run the deterministic engine, redact, audit, return the worksheet.

The consequential decision (the resulting entitlements, the SoD verdict, the approval chain) is
the pure :class:`~.access_engine.AccessEngine`; this layer adds the side effects the engine must
not have. It redacts before the audit write (a raw subject reference never reaches the WORM record
in the clear), records an already-redacted event, and returns the engine's result unchanged so
the API, the CLI and the agent all see the same worksheet. Rule R8 routing is the SURFACE's job
(every grant is consequential, so every surface routes in the same call that produced the result);
the service does not swallow it.

The engine is injected, so a test and the eval oracle drive the exact object the service runs.
"""

from __future__ import annotations

from functools import lru_cache

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.observability import ObservabilityTracerPort
from .access_engine import AccessEngine
from .kernel import AuditEvent, utcnow
from .models import AccessDecision, AccessRequest
from .packs import AccessPolicy, load_access_policy
from .pii import PII_PATTERNS, redacted_citations


@lru_cache(maxsize=1)
def default_access_policy() -> AccessPolicy:
    """The policy shipped under ``config/packs/access``, loaded once. Callers may inject one."""
    return load_access_policy()


def default_engine() -> AccessEngine:
    """An engine bound to the shipped policy (the offline default the surfaces build)."""
    return AccessEngine(default_access_policy())


#: One span per assessed request. Structural attributes only: see :meth:`AccessService.assess`.
_ACCESS_SPAN = "itsm.access"


class AccessService:
    """Assess an access request deterministically and record an already-redacted audit event."""

    def __init__(
        self,
        audit: AuditSinkPort,
        engine: AccessEngine | None = None,
        *,
        tracer: ObservabilityTracerPort,
    ) -> None:
        self._audit = audit
        self._engine = engine or default_engine()
        self._tracer = tracer

    def assess(self, request: AccessRequest, *, actor: str) -> AccessDecision:
        """Assess ``request`` deterministically and record the already-redacted audit event.

        The whole path runs inside one span. Its attributes are STRUCTURAL only, never the
        subject reference, the requested role or the held entitlements (the audit path masks
        those on purpose): a trace backend is not the WORM audit trail; it has no redaction
        stage, a wider read audience and no retention rule written against a regulator's
        requirement, so anything content-shaped that reaches a span has left the boundary
        the ``redact`` call below exists to hold, and left it silently.
        """
        with self._tracer.span(_ACCESS_SPAN, action="access", actor=actor):
            return self._assess(request, actor=actor)

    def _assess(self, request: AccessRequest, *, actor: str) -> AccessDecision:
        result = self._engine.assess(request)

        # Redact BEFORE the audit write, on EVERY content field the event carries and not just
        # the summary. Masking the summary and then passing `result.citations` straight through
        # is how the raw request text stayed in the WORM record: the fail-closed unknown-role
        # path quotes `requested_role` verbatim into a citation snippet, so the record kept
        # exactly what the line below had removed, in a store nothing can correct later.
        held = ",".join(request.current_entitlements)
        detail = (
            f"{result.summary} :: subject={request.subject_ref} "
            f"role={request.requested_role} held={held}"
        )
        self._audit.record(
            AuditEvent(
                action="access",
                actor=actor,
                decision=result.decision,
                severity=result.severity,
                redacted_summary=redact(detail, PII_PATTERNS),
                citations=redacted_citations(result.citations),
                timestamp=utcnow(),
            )
        )
        return result
