"""Each service-desk path opens ONE span, and no span carries content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit
store. So the value of tracing these paths depends entirely on the spans carrying
structural attributes only: which action, whose. A ticket's free text, a subject reference,
a requested role or a planted identifier reaching a span has left the boundary the
services' ``redact`` calls exist to hold, and it has left it silently.

Two orchestrators are pinned because both sit on real request paths: ticket triage (API,
CLI, agent tool, demo, eval) and access assessment (API, CLI, agent tool). They do not
nest: neither drives the other. The content cases drive the ticket whose text carries a
planted NRIC and an access request whose subject reference carries the same, so the checks
run against input that would actually leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from itsm_servicedesk_triage.config import Settings, build_container
from itsm_servicedesk_triage.domain.access_service import AccessService
from itsm_servicedesk_triage.domain.models import AccessRequest, TriageInput
from itsm_servicedesk_triage.domain.triage_service import TriageService
from itsm_servicedesk_triage.packs import default_access_engine, default_triage_engine

from tests.fixtures import sample_cases

#: Every attribute key each span is allowed to carry. A verdict that started explaining
#: itself on the span (a queue, a subject, a role) would widen these sets, which is the
#: point of asserting on the set rather than on the individual keys.
_TRIAGE_KEYS = {"action", "actor"}
_ACCESS_KEYS = {"action", "actor"}

#: An access request whose subject reference carries the planted identifier, mirroring the
#: redact-before-audit case in test_access_surface.py.
_PII_ACCESS_REQUEST = AccessRequest(
    request_ref="REQ-SPAN-1",
    subject_ref=f"person {sample_cases.PLANTED_NRIC}",
    requested_role="payments_maker",
    current_entitlements=("payment.approve",),
)


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _triage(case: TriageInput) -> _RecordingTracer:
    tracer = _RecordingTracer()
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = TriageService(container.audit, default_triage_engine(), tracer=tracer)  # type: ignore[arg-type]
    service.triage(case, actor=sample_cases.ACTOR)
    return tracer


def _assess(request: AccessRequest) -> _RecordingTracer:
    tracer = _RecordingTracer()
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = AccessService(container.audit, default_access_engine(), tracer=tracer)  # type: ignore[arg-type]
    service.assess(request, actor=sample_cases.ACTOR)
    return tracer


def _emitted(tracer: _RecordingTracer) -> str:
    """Every attribute KEY and VALUE that was emitted, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


def test_triaging_a_ticket_opens_exactly_one_named_span() -> None:
    tracer = _triage(sample_cases.ROUTINE_CASE)
    assert [name for name, _ in tracer.spans] == ["itsm.triage"]


def test_assessing_access_opens_exactly_one_named_span() -> None:
    tracer = _assess(_PII_ACCESS_REQUEST)
    assert [name for name, _ in tracer.spans] == ["itsm.access"]


def test_the_triage_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose triage is slow", and nothing more."""
    _, attributes = _triage(sample_cases.ROUTINE_CASE).spans[0]
    assert attributes["action"] == "triage"
    assert attributes["actor"] == sample_cases.ACTOR


def test_the_access_span_carries_the_structural_attributes_an_operator_needs() -> None:
    _, attributes = _assess(_PII_ACCESS_REQUEST).spans[0]
    assert attributes["action"] == "access"
    assert attributes["actor"] == sample_cases.ACTOR


@pytest.mark.parametrize(
    "case",
    [sample_cases.ROUTINE_CASE, sample_cases.ESCALATING_CASE, sample_cases.PII_CASE],
    ids=["routine", "escalating", "pii"],
)
def test_the_triage_attribute_set_is_a_fixed_allowlist_whatever_the_verdict(
    case: TriageInput,
) -> None:
    """An escalating ticket must not start attaching its queue, or its text, to the span."""
    for _, attributes in _triage(case).spans:
        assert set(attributes) == _TRIAGE_KEYS, (
            "a new span attribute appeared; confirm it is structural, then widen "
            "_TRIAGE_KEYS here deliberately"
        )


def test_the_access_attribute_set_is_a_fixed_allowlist() -> None:
    """A blocked grant must not start attaching its subject, or its role, to the span."""
    for _, attributes in _assess(_PII_ACCESS_REQUEST).spans:
        assert set(attributes) == _ACCESS_KEYS, (
            "a new span attribute appeared; confirm it is structural, then widen "
            "_ACCESS_KEYS here deliberately"
        )


def test_no_triage_span_attribute_carries_ticket_content_or_the_planted_identifier() -> None:
    """The ticket used here has an NRIC planted in its free text, so a leak would show."""
    emitted = _emitted(_triage(sample_cases.PII_CASE)).lower()
    forbidden = (
        sample_cases.PLANTED_NRIC,
        sample_cases.PII_CASE.text,
        sample_cases.PII_CASE.subject,
        "ops@gamma.example",
        "urgent breach",
    )
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal.lower() not in emitted, f"a span attribute carried {literal!r}"


def test_no_access_span_attribute_carries_the_subject_the_role_or_the_entitlements() -> None:
    """The audit path masks exactly these on purpose, so the span must never see them."""
    emitted = _emitted(_assess(_PII_ACCESS_REQUEST)).lower()
    forbidden = (
        sample_cases.PLANTED_NRIC,
        _PII_ACCESS_REQUEST.subject_ref,
        _PII_ACCESS_REQUEST.requested_role,
        *_PII_ACCESS_REQUEST.current_entitlements,
    )
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal.lower() not in emitted, f"a span attribute carried {literal!r}"


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    values = [
        value
        for tracer in (_triage(sample_cases.ESCALATING_CASE), _assess(_PII_ACCESS_REQUEST))
        for _, attributes in tracer.spans
        for value in attributes.values()
    ]
    assert values
    assert all(isinstance(value, str) for value in values)
