"""The deterministic access-provisioning engine: every eligibility verdict, in pure stdlib.

This is the other half of the vertical's differentiation, and the more consequential one. Given
an access request plus the policy pack, it resolves the requested role to its entitlements,
computes the entitlement set the subject WOULD hold, checks that set against the segregation-of-
duties matrix, and derives the approval chain, with NO model in the loop. An LLM may narrate this
worksheet; it can never decide eligibility or an approver.

The verdict shape is cribbed from ``human-review-console``'s maker-checker engine: collect
EVERY reason the grant may not proceed unreviewed (not short-circuited), so a reviewer sees all of
them at once, and empty means clean. This repo owns its policy as configuration (the pack); the
console owns none of it.

Fail closed, always. An unknown role yields NO verdict and routes to a human. And every grant is
CONSEQUENTIAL by construction: whatever the arithmetic says, ``requires_human_review`` is set and
the decision is ``ESCALATED``. The engine decides eligibility and the chain; a human disposes, and
nothing provisions before that disposition. The engine talks only to the pack: no ports, no I/O,
no audit write (the service layer owns those), so it is trivially replayable in a test and in the
eval oracle.
"""

from __future__ import annotations

from .kernel import Citation, Decision, Severity, VerdictStatus
from .models import AccessDecision, AccessRequest, SoDFinding
from .packs import AccessPolicy

#: Role risk tier -> the base severity of the review the grant routes to. An SoD conflict
#: overrides this to CRITICAL: a toxic combination is the most serious finding the engine makes.
_TIER_SEVERITY: dict[str, Severity] = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


class AccessEngine:
    """Decide access eligibility from the policy pack. Pure, deterministic, replayable."""

    def __init__(self, policy: AccessPolicy) -> None:
        self._policy = policy

    def assess(self, request: AccessRequest) -> AccessDecision:
        """Assess one access request. Never raises on unknown input; it fails closed to a human."""
        role = self._policy.role(request.requested_role)
        if role is None:
            return self._unknown_role(request)

        current = frozenset(e.strip().lower() for e in request.current_entitlements if e.strip())
        resulting = current | role.entitlements
        conflicts = self._policy.conflicts_for(resulting)
        findings = tuple(
            SoDFinding(
                code="segregation_of_duties",
                detail=conflict.detail,
                entitlements=tuple(sorted(conflict.entitlements)),
                citation=conflict.citation(),
            )
            for conflict in conflicts
        )
        eligible = not findings
        severity = Severity.CRITICAL if findings else _TIER_SEVERITY[role.risk_tier]
        chain = self._policy.chain_for(role.risk_tier)

        verdict = "eligible, pending approval" if eligible else "BLOCKED by segregation of duties"
        summary = (
            f"{request.subject_ref}: grant {role.role_id} ({role.risk_tier} risk) is {verdict}; "
            f"routed to {' -> '.join(chain)}"
        )
        citations = (role.citation(), *(f.citation for f in findings if f.citation is not None))
        return AccessDecision(
            subject=request.subject_ref,
            severity=severity,
            decision=Decision.ESCALATED,
            summary=summary,
            requires_human_review=True,
            citations=citations,
            status=VerdictStatus.COMPUTED,
            requested_role=role.role_id,
            role_risk_tier=role.risk_tier,
            resolved_entitlements=tuple(sorted(role.entitlements)),
            resulting_entitlements=tuple(sorted(resulting)),
            eligible=eligible,
            findings=findings,
            approval_chain=chain,
        )

    def _unknown_role(self, request: AccessRequest) -> AccessDecision:
        """No such role in the catalog: refuse to guess, carry no entitlement set, route up."""
        finding = SoDFinding(
            code="unknown_role",
            detail=(
                f"requested role {request.requested_role!r} is not in the access catalog; "
                "routed for human review rather than provisioning an unknown grant"
            ),
            entitlements=(),
            citation=Citation(
                source_id="engine:needs_info",
                title="Fail-closed: unknown role",
                snippet=request.requested_role,
            ),
        )
        chain = self._policy.chain_for("critical")
        summary = (
            f"{request.subject_ref}: requested role {request.requested_role!r} is unknown; "
            f"routed to {' -> '.join(chain)}"
        )
        return AccessDecision(
            subject=request.subject_ref,
            severity=Severity.MEDIUM,
            decision=Decision.ESCALATED,
            summary=summary,
            requires_human_review=True,
            citations=(finding.citation,) if finding.citation is not None else (),
            status=VerdictStatus.NEEDS_INFO,
            requested_role=request.requested_role,
            role_risk_tier="",
            resolved_entitlements=(),
            resulting_entitlements=tuple(
                sorted(e.strip().lower() for e in request.current_entitlements if e.strip())
            ),
            eligible=False,
            findings=(finding,),
            approval_chain=chain,
        )
