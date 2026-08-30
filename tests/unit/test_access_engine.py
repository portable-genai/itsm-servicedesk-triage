"""The deterministic access engine: SoD verdicts, fail-closed, all findings, provable red.

The access engine is the more consequential half of this vertical. These tests hold the
invariants the plan's slice 3 rests on:

* the verdict is computed from the pack alone, replayably, with no model in the loop;
* a toxic combination is BLOCKED, including one that only forms in union with what the subject
  already holds, and a request that merely LOOKS toxic but is not stays eligible (precision);
* every reason is collected, not short-circuited, so a reviewer sees all of them at once;
* an unknown role FAILS CLOSED to a human rather than guessing;
* every grant is consequential: whatever the arithmetic says, it escalates and routes;
* the SoD precision metric can be driven RED by injecting a wildcard into the conflict matrix,
  which is the plan's own can-go-red proof for this engine.
"""

from __future__ import annotations

import dataclasses

from agent_eval_kit import assert_can_go_red

from itsm_servicedesk_triage.domain.access_engine import (
    AccessEngine,
)
from itsm_servicedesk_triage.domain.kernel import (
    Decision,
    Severity,
    VerdictStatus,
)
from itsm_servicedesk_triage.domain.models import (
    AccessDecision,
    AccessRequest,
)
from itsm_servicedesk_triage.domain.packs import AccessPolicy, SoDConflict
from itsm_servicedesk_triage.packs import load_access_policy


def _engine() -> AccessEngine:
    return AccessEngine(load_access_policy())


def _request(role: str, current: tuple[str, ...] = ()) -> AccessRequest:
    return AccessRequest(
        request_ref="REQ-T",
        subject_ref="person-test",
        requested_role=role,
        current_entitlements=current,
    )


def _conflict_ids(decision: AccessDecision) -> set[str]:
    """The conflict ids the engine cited, read off each finding's citation snippet."""
    return {f.citation.snippet for f in decision.findings if f.citation is not None}


def test_a_clean_grant_is_eligible_with_no_findings() -> None:
    decision = _engine().assess(_request("service_desk_agent"))
    assert decision.eligible is True
    assert decision.findings == ()
    assert decision.status is VerdictStatus.COMPUTED


def test_a_toxic_maker_checker_combination_is_blocked() -> None:
    # payments_maker grants payment.create; the subject already approves payments. The union is
    # the classic maker-checker toxic pair, and it must block.
    decision = _engine().assess(_request("payments_maker", ("payment.approve",)))
    assert decision.eligible is False
    assert "sod-pay-maker-checker" in _conflict_ids(decision)


def test_a_conflict_that_only_forms_with_an_existing_grant_is_still_caught() -> None:
    # Neither role alone holds both members of sod-vendor-and-pay; the conflict exists only
    # because the subject already holds vendor.create.
    clean = _engine().assess(_request("payments_maker"))
    assert clean.eligible is True
    toxic = _engine().assess(_request("payments_maker", ("vendor.create",)))
    assert toxic.eligible is False
    assert "sod-vendor-and-pay" in _conflict_ids(toxic)


def test_a_request_that_only_looks_toxic_stays_eligible() -> None:
    # payments_approver holds payment.approve and payment.view. Without payment.create,
    # ledger.post or iam.grant there is no conflict, so a precise engine must NOT block it.
    decision = _engine().assess(_request("payments_approver", ("payment.view",)))
    assert decision.eligible is True
    assert decision.findings == ()


def test_every_reason_is_collected_not_short_circuited() -> None:
    # identity_admin plus a subject already holding both payment.approve and payment.create
    # trips TWO conflicts at once; both must be reported, not just the first found.
    decision = _engine().assess(_request("identity_admin", ("payment.approve", "payment.create")))
    assert decision.eligible is False
    assert {"sod-iam-self-grant", "sod-pay-maker-checker"} <= _conflict_ids(decision)


def test_an_unknown_role_fails_closed_to_a_human() -> None:
    decision = _engine().assess(_request("wizard_supreme"))
    assert decision.eligible is False
    assert decision.status is VerdictStatus.NEEDS_INFO
    assert decision.requires_human_review is True
    assert decision.findings and decision.findings[0].code == "unknown_role"


def test_every_grant_is_consequential_whatever_the_verdict() -> None:
    for req in (
        _request("service_desk_agent"),  # eligible
        _request("payments_maker", ("payment.approve",)),  # blocked
        _request("wizard_supreme"),  # unknown
    ):
        decision = _engine().assess(req)
        assert decision.requires_human_review is True, "an access grant escaped human review"
        assert decision.decision is Decision.ESCALATED


def test_a_blocked_grant_is_the_most_severe_band() -> None:
    decision = _engine().assess(_request("payments_maker", ("payment.approve",)))
    assert decision.severity is Severity.CRITICAL


def test_the_result_carries_citations() -> None:
    decision = _engine().assess(_request("payments_maker", ("payment.approve",)))
    assert decision.citations, "a blocked grant with no provenance is not shippable"


def test_the_decision_is_deterministic_on_replay() -> None:
    req = _request("payments_maker", ("payment.approve", "vendor.create"))
    first = _engine().assess(req)
    second = _engine().assess(req)
    assert first == second


# --------------------------------------------------------------------------------------------- #
# The plan's can-go-red proof: a wildcard conflict must drop SoD precision below its bar.
# --------------------------------------------------------------------------------------------- #

#: A tiny labelled set: two clean payments_approver grants and one toxic maker-checker grant. The
#: labels are the independent oracle; nothing here reads the engine's own verdict as truth.
_GOLDEN: tuple[tuple[AccessRequest, bool], ...] = (
    (_request("payments_approver"), True),
    (_request("payments_approver", ("payment.view",)), True),
    (_request("payments_maker", ("payment.approve",)), False),
)


def _sod_precision(policy: AccessPolicy) -> float:
    engine = AccessEngine(policy)
    tp = fp = 0
    for req, expected_eligible in _GOLDEN:
        blocked = not engine.assess(req).eligible
        if blocked and not expected_eligible:
            tp += 1
        elif blocked and expected_eligible:
            fp += 1
    denom = tp + fp
    return tp / denom if denom else 1.0


def _wildcard(policy: AccessPolicy) -> AccessPolicy:
    """Inject a conflict on a pair a clean role legitimately holds, so it over-blocks."""
    conflict = SoDConflict(
        conflict_id="wildcard-test-only",
        entitlements=frozenset({"payment.view", "payment.approve"}),
        detail="TEST-ONLY wildcard that also blocks a clean grant",
        source_id=policy.source_id,
        source_title=policy.source_title,
        citation_clause="WILD",
    )
    return dataclasses.replace(policy, conflicts=(*policy.conflicts, conflict))


def test_sod_precision_can_go_red_under_a_wildcard_conflict() -> None:
    policy = load_access_policy()
    assert_can_go_red(
        _sod_precision,
        green=policy,  # the shipped matrix: only the toxic grant is blocked, precision 1.0
        red=_wildcard(policy),  # the wildcard also blocks two clean grants, precision falls
        threshold=1.0,
        metric="sod_precision",
    )
