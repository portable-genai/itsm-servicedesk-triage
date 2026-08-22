"""Vertical artifact models: this service's own request and result types.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

Two verticals live here, each with a pure deterministic engine (``triage_engine`` and
``access_engine``) and its own request/result pair:

* TICKET TRIAGE: an inbound ticket, plus the model's ADVISORY classification, in; a
  deterministic (category, priority, queue) routing worksheet out. The engine wins any
  disagreement with the model.
* ACCESS PROVISIONING: an access request in; a deterministic entitlement / segregation-of-duties
  worksheet out. Every grant is consequential and routes to a human.

A fork building a different vertical rewrites this module and keeps ``kernel.py`` untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .kernel import Citation, Decision, Severity, VerdictStatus

# --------------------------------------------------------------------------------------------- #
# The ticket-triage vertical: an inbound ticket plus an advisory classification in, a
# deterministic routing worksheet out.
# --------------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TicketSignals:
    """The model's ADVISORY classification of a ticket. Every field is a suggestion.

    An LLM (or a channel adapter's own classifier) may fill these in from the ticket text. The
    deterministic engine reads them only to DETECT disagreement: it recomputes category, priority
    and queue from the taxonomy pack itself and its own computation wins, so a wrong or adversarial
    model label can never change where a ticket lands. Empty strings mean the model offered no
    opinion.
    """

    category: str = ""
    priority: str = ""
    affected_service: str = ""


@dataclass(frozen=True, slots=True)
class TriageInput:
    """One inbound ticket to triage: a subject, its free-text body, and any advisory signals.

    ``subject`` is the requester or ticket reference (obviously synthetic in tests); ``text`` is
    the ticket body the taxonomy is matched against. ``signals`` carries the model's advisory
    classification and defaults to no opinion, so an intake path with no model still triages.
    """

    subject: str
    text: str
    signals: TicketSignals = field(default_factory=TicketSignals)


@dataclass(frozen=True, slots=True)
class TriageResult:
    """The deterministic triage worksheet plus the review-routable decision fields.

    The first block is what rule R8 routing and the audit trail read (it satisfies
    :class:`~.kernel.ReviewableResult`); the second block is the routing worksheet a service-desk
    agent inspects. ``model_agreed`` is ``False`` when the model's advisory label differed from
    the engine's computation, which is itself surfaced (a persistent disagreement is a taxonomy
    gap worth a human's eye), never silently reconciled.
    """

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    citations: tuple[Citation, ...] = ()

    status: VerdictStatus = VerdictStatus.COMPUTED
    category: str = ""
    priority: str = ""
    affected_service: str = ""
    queue: str = ""
    model_agreed: bool = True
    rule_id: str = ""


# --------------------------------------------------------------------------------------------- #
# The access-provisioning vertical: an access request in, a deterministic entitlement / SoD
# worksheet out. Every grant is consequential.
# --------------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AccessRequest:
    """One access request: who would receive which role, and what they already hold.

    ``subject_ref`` is an opaque, fictional reference to the person who would receive access,
    never a real identifier. ``current_entitlements`` are the entitlements the subject holds
    TODAY; the engine reasons over the UNION of those and the requested role's entitlements, so a
    toxic combination that only forms in combination with an existing grant is still caught.
    """

    request_ref: str
    subject_ref: str
    requested_role: str
    current_entitlements: tuple[str, ...] = ()
    #: The date the verdict is computed AS OF, so a replay does not silently pick a different
    #: policy version. Reserved for future effective-window support; recorded for the audit trail.
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class SoDFinding:
    """One reason a grant may not proceed unreviewed, with the entitlements that triggered it.

    ``code`` is a stable machine reason (``segregation_of_duties``, ``unknown_role``); ``detail``
    is the human-readable explanation from the policy pack; ``entitlements`` names the specific
    toxic combination or the offending entitlement, so a reviewer sees exactly what conflicted.
    """

    code: str
    detail: str
    entitlements: tuple[str, ...] = ()
    citation: Citation | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """The deterministic access worksheet plus the review-routable decision fields.

    The first block satisfies :class:`~.kernel.ReviewableResult`. ``eligible`` is the engine's
    verdict on whether the grant is free of segregation-of-duties conflicts; it is NOT permission
    to provision. Every grant is consequential, so ``requires_human_review`` is always ``True``
    and ``decision`` is always ``ESCALATED``: the engine decides eligibility and the approval
    chain, and a human disposes. ``resulting_entitlements`` is the union the reviewer would be
    approving; ``findings`` is empty exactly when ``eligible`` is ``True``.
    """

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    citations: tuple[Citation, ...] = ()

    status: VerdictStatus = VerdictStatus.COMPUTED
    requested_role: str = ""
    role_risk_tier: str = ""
    resolved_entitlements: tuple[str, ...] = ()
    resulting_entitlements: tuple[str, ...] = ()
    eligible: bool = False
    findings: tuple[SoDFinding, ...] = ()
    approval_chain: tuple[str, ...] = ()
