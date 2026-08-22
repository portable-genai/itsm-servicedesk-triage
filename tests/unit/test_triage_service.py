"""The deterministic triage service: severity bands, soft escalation, redact-before-audit."""

from __future__ import annotations

import json

from pii_kit import pack_leak

from itsm_servicedesk_triage.adapters.local.audit import (
    LocalAuditAdapter,
)
from itsm_servicedesk_triage.adapters.local.review_router import (
    LocalReviewRouter,
)
from itsm_servicedesk_triage.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from itsm_servicedesk_triage.agent import (
    triage_case,
)
from itsm_servicedesk_triage.config import (
    Settings,
)
from itsm_servicedesk_triage.domain.kernel import (
    Decision,
    Severity,
)
from itsm_servicedesk_triage.domain.models import (
    TriageInput,
)
from itsm_servicedesk_triage.domain.pii import (
    PII_PATTERNS,
)
from itsm_servicedesk_triage.domain.triage_service import (
    TriageService,
)

from tests.conftest import audit_content, local_settings, outbound_content
from tests.fixtures import sample_cases


def _service() -> tuple[TriageService, LocalAuditAdapter]:
    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    return TriageService(audit, tracer=LocalNoopTracerAdapter(settings)), audit


def _severity(text: str) -> Severity:
    service, _ = _service()
    return service.triage(TriageInput("X", text), actor="a").severity


def test_severity_bands_are_deterministic() -> None:
    assert _severity("possible fraud") is Severity.CRITICAL
    assert _severity("data breach") is Severity.HIGH
    assert _severity("billing dispute") is Severity.MEDIUM
    assert _severity("all fine") is Severity.LOW


def test_high_and_critical_escalate_softly() -> None:
    service, _ = _service()
    high = service.triage(TriageInput("X", "urgent leak"), actor="a")
    assert high.decision is Decision.ESCALATED
    assert high.requires_human_review is True

    low = service.triage(TriageInput("X", "routine note"), actor="a")
    assert low.decision is Decision.ALLOWED
    assert low.requires_human_review is False


def test_pii_is_redacted_before_the_audit_write() -> None:
    service, audit = _service()
    service.triage(
        TriageInput("Gamma LLP", "urgent breach, NRIC S1234567D on file"),
        actor="analyst@bank.example",
    )
    records = audit.log.read_all()
    assert records, "an audit event should have been recorded"
    summary = records[-1]["redacted_summary"]
    # The raw identifier never reaches the WORM record; the actor is the verified principal.
    assert "S1234567D" not in summary
    assert "REDACTED" in summary
    assert records[-1]["actor"] == "analyst@bank.example"
    assert audit.log.verify_chain().ok


def test_triage_masks_every_sink_the_ticket_leaves_by() -> None:
    """C3, all three sinks at once: the WORM record, the outbound review, the model's context.

    The one above scores ``redacted_summary`` and nothing else, which is precisely how this got
    through: the summary was masked while ``citations=result.citations`` handed the SAME audit
    event the engine's untouched evidence citation, whose snippet is the raw ticket body and whose
    ``source_id`` is ``ticket:<subject>``. A record the redactor had just cleaned kept the
    identifier one field over, permanently, in a store that cannot be edited afterwards.

    So the assertions here are per SINK rather than per field, and the planted identifiers sit in
    the two places a caller actually supplies text: the subject line and the ticket body. The
    fix redacts once where the engine's result crosses OUT of the pure domain, so a fourth sink
    added later inherits the boundary instead of needing to remember it.
    """
    settings = local_settings()
    audit = LocalAuditAdapter(settings)
    router = LocalReviewRouter(settings)
    result = TriageService(audit, tracer=LocalNoopTracerAdapter(settings)).triage(
        sample_cases.PII_TICKET, actor=sample_cases.ACTOR
    )
    router.route(result, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)

    rows = list(audit.log.read_all())
    assert rows, "guard the guard: nothing is proved if no audit event was written"
    # Scan the CONTENT fields, never the whole row: ``actor`` is the VERIFIED principal and is an
    # address by design, so a blanket scan could never go green and would be switched off.
    stored = audit_content(rows)
    assert sample_cases.PLANTED_NRIC not in stored, "a raw NRIC reached the WORM record"
    assert sample_cases.PLANTED_EMAIL not in stored, "a raw email reached the WORM record"
    assert not pack_leak(stored, PII_PATTERNS), "an unplanted pattern reached the WORM record"

    pending = router.outbox.pending()
    assert pending, "guard the guard: an escalating ticket must have produced a review"
    wire = outbound_content(pending[0].review)
    assert sample_cases.PLANTED_NRIC not in wire, "a raw NRIC left for the shared console"
    assert sample_cases.PLANTED_EMAIL not in wire, "a raw email left for the shared console"
    assert not pack_leak(wire, PII_PATTERNS), "an unplanted pattern left for the shared console"

    to_model = json.dumps(
        triage_case(
            subject=sample_cases.PII_TICKET.subject,
            text=sample_cases.PII_TICKET.text,
            actor=sample_cases.ACTOR,
            tenant=sample_cases.TENANT,
            settings=settings,
        ),
        default=str,
    )
    assert sample_cases.PLANTED_NRIC not in to_model, "a raw NRIC reached the model's context"
    assert sample_cases.PLANTED_EMAIL not in to_model, "a raw email reached the model's context"

    # Redaction masks, it does not drop: the route is still evidenced and still traceable.
    assert rows[-1]["citations"], "a redacted audit record still carries its citations"
    assert "security_incident" in stored, "a PII-free citation survived redaction intact"
