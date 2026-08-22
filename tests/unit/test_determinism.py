"""Determinism: the consequential numbers come from pure code, never from the model.

The house rule is "with the generation adapter stubbed out, the numeric output is IDENTICAL."
This vertical has no in-pipeline generation at all: the deterministic engines own every band,
queue, priority and eligibility verdict, and the model's ONLY channel is the advisory
``TicketSignals`` a channel adapter may attach. So the sharpest form of the invariant here is
that those advisory signals, however wrong or adversarial, cannot move a single consequential
field. If they could, a model would be producing a number, which is exactly what the
architecture forbids.
"""

from __future__ import annotations

from itsm_servicedesk_triage.domain.models import (
    TicketSignals,
    TriageInput,
    TriageResult,
)
from itsm_servicedesk_triage.domain.packs import (
    load_triage_pack,
)
from itsm_servicedesk_triage.domain.triage_engine import (
    TriageEngine,
)

#: A few tickets that land in different bands, so the proof is not about one lucky category.
_TEXTS: tuple[tuple[str, str], ...] = (
    ("Acme (FICTIONAL)", "urgent data breach reported by the branch"),
    ("Beta (FICTIONAL)", "routine note about a stationery order"),
    ("Gamma (FICTIONAL)", "suspected fraud flagged by screening"),
    ("Delta (FICTIONAL)", "billing dispute over a duplicate invoice"),
    ("Eta (FICTIONAL)", "general question, nothing wrong"),
)

#: Deliberately hostile advisory signals: a confidently wrong category, a maxed-out priority and
#: an unrelated service. A model that could steer the route would steer it here.
_ADVERSARIAL = TicketSignals(
    category="fraud_or_sanctions",
    priority="p1",
    affected_service="financial_crime",
)

#: The subset of a result that is CONSEQUENTIAL: the band, the routing and the escalation. These
#: are the fields a model may never influence. ``model_agreed`` is deliberately excluded because
#: recording that the model disagreed is the whole point, and it changes no downstream action.
_CONSEQUENTIAL = (
    "severity",
    "decision",
    "requires_human_review",
    "category",
    "priority",
    "affected_service",
    "queue",
    "status",
    "citations",
)


def _consequential(result: TriageResult) -> tuple[object, ...]:
    return tuple(getattr(result, name) for name in _CONSEQUENTIAL)


def test_advisory_signals_cannot_change_a_single_consequential_field() -> None:
    engine = TriageEngine(load_triage_pack())
    for subject, text in _TEXTS:
        without = engine.triage(TriageInput(subject=subject, text=text))
        with_lie = engine.triage(TriageInput(subject=subject, text=text, signals=_ADVERSARIAL))
        assert _consequential(without) == _consequential(with_lie), (
            f"{subject!r}: an advisory model label moved a consequential field; the engine, not "
            "the model, must own every number"
        )


def test_the_engine_is_replayable() -> None:
    engine = TriageEngine(load_triage_pack())
    ticket = TriageInput(subject="Acme (FICTIONAL)", text="urgent data breach")
    assert engine.triage(ticket) == engine.triage(ticket)


def test_only_the_disagreement_flag_reflects_the_model() -> None:
    """The one field the advisory label MAY move is ``model_agreed``, and only that field."""
    engine = TriageEngine(load_triage_pack())
    ticket = TriageInput(
        subject="Acme (FICTIONAL)",
        text="urgent data breach",
        signals=TicketSignals(category="hardware"),  # wrong on purpose
    )
    result = engine.triage(ticket)
    assert result.model_agreed is False
    assert result.category == "security_incident", "the engine's own computation must still win"
