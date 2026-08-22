"""The access vertical's surfaces: redact-before-audit, R8 routing, API and agent parity.

Slice 3 says every access grant is consequential and routes to Hrz7, and the redact-before-
anything rule applies to the access path exactly as it does to triage. These tests hold that on
every surface: the service masks before the audit write, the local router puts a redacted,
``access``-labelled payload on the wire, a blocked (critical) grant demands dual control, the API
always returns a routing reference, and the agent tool masks its result before it can reach a
model.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from pii_kit import pack_leak

from itsm_servicedesk_triage.adapters.local.review_router import (
    LocalReviewRouter,
)
from itsm_servicedesk_triage.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from itsm_servicedesk_triage.agent import (
    assess_access,
)
from itsm_servicedesk_triage.domain.access_service import (
    AccessService,
)
from itsm_servicedesk_triage.domain.models import (
    AccessRequest,
)
from itsm_servicedesk_triage.domain.pii import (
    PII_PATTERNS,
)

from tests.conftest import audit_content, local_settings, outbound_content
from tests.fixtures import sample_cases


def _service() -> AccessService:
    from itsm_servicedesk_triage.config import build_container

    container = build_container(local_settings())
    return AccessService(container.audit, tracer=container.tracer)


def _request(role: str, current: tuple[str, ...] = (), subject: str = "person-x") -> AccessRequest:
    return AccessRequest(
        request_ref="REQ-1",
        subject_ref=subject,
        requested_role=role,
        current_entitlements=current,
    )


def test_the_service_redacts_before_the_audit_write() -> None:
    from itsm_servicedesk_triage.adapters.local.audit import LocalAuditAdapter

    audit = LocalAuditAdapter(local_settings())
    service = AccessService(audit, tracer=LocalNoopTracerAdapter(local_settings()))
    # A subject reference that (unusually) carries a raw identifier must be masked on the way to
    # the WORM record, exactly like the triage path.
    service.assess(
        _request(
            "payments_maker", ("payment.approve",), subject=f"person {sample_cases.PLANTED_NRIC}"
        ),
        actor=sample_cases.ACTOR,
    )
    record = audit.log.read_all()[-1]
    assert sample_cases.PLANTED_NRIC not in record["redacted_summary"]
    assert "REDACTED" in record["redacted_summary"]
    assert record["actor"] == sample_cases.ACTOR
    assert audit.log.verify_chain().ok


def test_access_masks_every_sink_the_request_leaves_by() -> None:
    """C3, all three sinks at once: the WORM record, the outbound review, the model's context.

    The test above scores ``redacted_summary`` and nothing else, which is how this survived:
    ``citations=result.citations`` handed the SAME audit event the engine's untouched citations,
    and the fail-closed unknown-role path quotes the caller's ``requested_role`` VERBATIM into a
    citation snippet. The summary was masked, the citation stored beside it in the same immutable
    row was not, and nothing could edit the row afterwards.

    The assertions are per SINK rather than per field, and the identifiers sit where a caller
    actually supplies text. The fix redacts once where the decision crosses OUT of the pure
    domain, so a later sink inherits the boundary rather than having to remember it.
    """
    from itsm_servicedesk_triage.adapters.local.audit import LocalAuditAdapter

    settings = local_settings()
    audit = LocalAuditAdapter(settings)
    router = LocalReviewRouter(settings)
    decision = AccessService(audit, tracer=LocalNoopTracerAdapter(settings)).assess(
        sample_cases.PII_ACCESS_REQUEST, actor=sample_cases.ACTOR
    )
    router.route(decision, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT, action="access")

    rows = list(audit.log.read_all())
    assert rows, "guard the guard: nothing is proved if no audit event was written"
    # The CONTENT fields only. ``actor`` is the VERIFIED principal and is an address by design, so
    # a blanket scan over the row could never go green and would end up switched off.
    stored = audit_content(rows)
    assert sample_cases.PLANTED_NRIC not in stored, "a raw NRIC reached the WORM record"
    assert sample_cases.PLANTED_EMAIL not in stored, "a raw email reached the WORM record"
    assert not pack_leak(stored, PII_PATTERNS), "an unplanted pattern reached the WORM record"

    pending = router.outbox.pending()
    assert pending, "guard the guard: every access grant routes, so a review must exist"
    wire = outbound_content(pending[0].review)
    assert sample_cases.PLANTED_NRIC not in wire, "a raw NRIC left for the shared console"
    assert sample_cases.PLANTED_EMAIL not in wire, "a raw email left for the shared console"
    assert not pack_leak(wire, PII_PATTERNS), "an unplanted pattern left for the shared console"

    to_model = json.dumps(
        assess_access(
            request_ref=sample_cases.PII_ACCESS_REQUEST.request_ref,
            subject_ref=sample_cases.PII_ACCESS_REQUEST.subject_ref,
            requested_role=sample_cases.PII_ACCESS_REQUEST.requested_role,
            current_entitlements=list(sample_cases.PII_ACCESS_REQUEST.current_entitlements),
            actor=sample_cases.ACTOR,
            tenant=sample_cases.TENANT,
            settings=settings,
        ),
        default=str,
    )
    assert sample_cases.PLANTED_NRIC not in to_model, "a raw NRIC reached the model's context"
    assert sample_cases.PLANTED_EMAIL not in to_model, "a raw email reached the model's context"

    # Redaction masks, it does not drop: the refusal is still evidenced and still traceable.
    assert rows[-1]["citations"], "a redacted audit record still carries its citations"
    assert "unknown role" in stored.lower(), "a PII-free citation survived redaction intact"


def test_every_access_grant_is_routed_as_an_access_review() -> None:
    router = LocalReviewRouter(local_settings())
    decision = _service().assess(_request("service_desk_agent"), actor=sample_cases.ACTOR)
    ref = router.route(
        decision, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT, action="access"
    )
    assert ref, "an access grant must return a routing reference"
    review = router.outbox.pending()[0].review
    assert review.action == "itsm_servicedesk_triage:access"
    assert "access" in review.source_key
    assert review.maker == sample_cases.ACTOR
    assert review.tenant == sample_cases.TENANT


def test_a_blocked_grant_demands_dual_control() -> None:
    router = LocalReviewRouter(local_settings())
    decision = _service().assess(
        _request("payments_maker", ("payment.approve",)), actor=sample_cases.ACTOR
    )
    router.route(decision, maker=sample_cases.ACTOR, action="access")
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_access_payload_is_redacted_before_it_leaves_the_process() -> None:
    router = LocalReviewRouter(local_settings())
    decision = _service().assess(
        _request(
            "payments_maker", ("payment.approve",), subject=f"person {sample_cases.PLANTED_NRIC}"
        ),
        actor=sample_cases.ACTOR,
    )
    router.route(decision, maker=sample_cases.ACTOR, action="access")
    wire = repr(router.outbox.pending()[0].review.to_payload())
    assert sample_cases.PLANTED_NRIC not in wire
    assert "REDACTED" in wire


def test_the_api_always_routes_an_access_decision(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/access",
        json={
            "request_ref": "REQ-9",
            "subject_ref": "person-0009",
            "requested_role": "payments_maker",
            "current_entitlements": ["payment.approve"],
        },
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_human_review"] is True
    assert body["eligible"] is False
    assert body["review_ref"], "an access decision with no routing reference went nowhere"
    assert any(f["code"] == "segregation_of_duties" for f in body["findings"])


def test_the_api_routes_even_a_clean_grant(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/access",
        json={
            "request_ref": "REQ-10",
            "subject_ref": "person-0010",
            "requested_role": "service_desk_agent",
        },
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible"] is True
    assert body["requires_human_review"] is True
    assert body["review_ref"], "an eligible grant is still consequential and must route"


def test_the_agent_tool_routes_and_masks_before_reaching_a_model() -> None:
    result = assess_access(
        request_ref="REQ-11",
        subject_ref=f"person {sample_cases.PLANTED_NRIC}",
        requested_role="payments_maker",
        current_entitlements=["payment.approve"],
        settings=local_settings(),
    )
    assert result["review_ref"], "the agent surface flagged an access grant it never routed"
    rendered = repr(result)
    assert sample_cases.PLANTED_NRIC not in rendered
    assert "REDACTED" in rendered
