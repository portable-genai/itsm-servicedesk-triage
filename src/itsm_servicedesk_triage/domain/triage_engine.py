"""The deterministic triage engine: every routing decision, in pure stdlib.

This is one half of the vertical's differentiation. Given an inbound ticket plus the model's
ADVISORY classification, it computes the category, the priority, the severity and the QUEUE from
the taxonomy pack, with NO model in the loop. An LLM (or a channel adapter) may suggest a
category; the engine recomputes from the ticket text itself and its computation WINS, so a wrong
or adversarial model label can never change where a ticket lands. That is the extract-then-decide
split ``credit-memo-drafting``'s covenant service uses: the model extracts, the engine
decides.

Deterministic and replayable: the same (ticket, pack) always yields the same route. Severity is a
pure function of the matched category's priority band; no keyword modifier can lift a ticket above
the band its category declares, so an "urgent" data-breach report stays HIGH rather than
manufacturing the CRITICAL band only a live financial-crime signal earns. The engine talks only to
the pack; no ports, no I/O, no audit write (the service layer owns those), so it is trivially
replayable in a test and in the eval oracle. Matching is first-category-wins over the pack's
declared order, so a more specific / more severe category placed earlier takes precedence.

Every result carries two citations: the taxonomy clause that decided the route, and a "ticket
description" evidence citation quoting the inbound text. The evidence snippet is the RAW ticket
excerpt; the redact-before-anything rule is honoured at every BOUNDARY that carries it outward
(the audit write, the outbound review payload, the agent tool result), never inside this pure
engine, exactly as the reference build keeps the raw description in the result and masks it on the
way out.
"""

from __future__ import annotations

from .kernel import Citation, Decision, Severity, VerdictStatus
from .models import TriageInput, TriageResult
from .packs import TriageCategory, TriagePack

#: Bands whose severity escalates a ticket to a human by construction.
_ESCALATING_SEVERITIES = frozenset({Severity.HIGH, Severity.CRITICAL})
#: How much of the inbound text the evidence citation carries. Enough for a reviewer to recognise
#: the ticket, bounded so a pathological body cannot bloat every downstream payload.
_EVIDENCE_CHARS = 240


class TriageEngine:
    """Route a ticket from the taxonomy pack. Pure, deterministic, replayable."""

    def __init__(self, pack: TriagePack) -> None:
        self._pack = pack

    def triage(self, ticket: TriageInput) -> TriageResult:
        """Compute the route for one ticket. Never raises on unknown input; it fails to default."""
        text = f"{ticket.subject}\n{ticket.text}".lower()
        matched = self._match(text)
        if matched is None:
            return self._default(ticket)

        priority = matched.priority
        severity = self._severity(priority)
        escalate = severity in _ESCALATING_SEVERITIES
        agreed = self._model_agreed(ticket, matched)
        summary = (
            f"{ticket.subject}: {matched.category_id} / {priority} -> queue {matched.queue} "
            f"(service {matched.affected_service})"
        )
        return TriageResult(
            subject=ticket.subject,
            severity=severity,
            decision=Decision.ESCALATED if escalate else Decision.ALLOWED,
            summary=summary,
            requires_human_review=escalate,
            citations=(matched.citation(), self._evidence(ticket)),
            status=VerdictStatus.COMPUTED,
            category=matched.category_id,
            priority=priority,
            affected_service=matched.affected_service,
            queue=matched.queue,
            model_agreed=agreed,
            rule_id=matched.category_id,
        )

    def _match(self, text: str) -> TriageCategory | None:
        """The first category whose keyword appears in the ticket text, or ``None``."""
        for category in self._pack.categories:
            if any(keyword in text for keyword in category.keywords):
                return category
        return None

    def _severity(self, priority: str) -> Severity:
        return Severity(self._pack.priority_severity[priority])

    def _evidence(self, ticket: TriageInput) -> Citation:
        """The inbound ticket text, quoted as evidence for the route.

        The snippet is the RAW excerpt; every boundary that carries it outward redacts it (the
        audit write, the outbound review payload, the agent tool result), so a reviewer sees the
        ticket in context while no raw identifier ever reaches a WORM record or the shared console.
        """
        excerpt = ticket.text.strip()[:_EVIDENCE_CHARS]
        return Citation(
            source_id=f"ticket:{ticket.subject}",
            title="Ticket description",
            snippet=excerpt,
        )

    def _model_agreed(self, ticket: TriageInput, matched: TriageCategory) -> bool:
        """Did the model's advisory category match the engine's? No opinion counts as agreement.

        The model NEVER changes the route; this only records whether it disagreed, so a persistent
        mismatch (a taxonomy gap, or a model drifting) is visible rather than silently absorbed.
        """
        advised = ticket.signals.category.strip().lower()
        return not advised or advised == matched.category_id

    def _default(self, ticket: TriageInput) -> TriageResult:
        """No category matched: route to the default queue, still deterministic and still real.

        The default queue is a real queue a human works, not a silent drop. ``model_agreed``
        records whether the model offered a category the engine could not corroborate, which is
        exactly the signal a taxonomy owner wants.
        """
        priority = self._pack.default_priority
        severity = self._severity(priority)
        escalate = severity in _ESCALATING_SEVERITIES
        agreed = not ticket.signals.category.strip()
        summary = (
            f"{ticket.subject}: {self._pack.default_category} / {priority} -> queue "
            f"{self._pack.default_queue} (no taxonomy match)"
        )
        return TriageResult(
            subject=ticket.subject,
            severity=severity,
            decision=Decision.ESCALATED if escalate else Decision.ALLOWED,
            summary=summary,
            requires_human_review=escalate,
            citations=(self._pack.default_citation(), self._evidence(ticket)),
            status=VerdictStatus.COMPUTED,
            category=self._pack.default_category,
            priority=priority,
            affected_service=self._pack.default_affected_service,
            queue=self._pack.default_queue,
            model_agreed=agreed,
            rule_id="default",
        )
