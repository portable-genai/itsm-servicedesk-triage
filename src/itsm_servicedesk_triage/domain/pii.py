"""The PII pattern set this vertical redacts with, plus the one helper that applies it.

Row selection and ORDER are per-vertical (the commons deliberately does not bake them in): here
the national-ID rows run first and the universal email/phone rows last. A vertical with a
bare-digit account catch-all would order that last so it does not subsume a national id.

:func:`redacted_citations` lives here rather than in either service because the two services are
not two boundaries: they are two callers of the SAME one, and a rule written twice is a rule that
holds until somebody adds a third caller.
"""

from __future__ import annotations

from pii_kit import UNIVERSAL_PATTERNS, Pattern, national_patterns_for, redact

from .kernel import Citation

# The jurisdictions this deployment serves (override per client). Obviously synthetic data only.
JURISDICTIONS: tuple[str, ...] = ("SG", "HK", "JP", "AU")

PII_PATTERNS: tuple[Pattern, ...] = (
    *national_patterns_for(JURISDICTIONS),
    *UNIVERSAL_PATTERNS,
)


def redacted_citations(citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
    """Mask EVERY string a citation carries, as it crosses out of the pure domain.

    The engines build their evidence citations out of the caller's own text on purpose (see
    ``triage_engine._evidence``), and for a while every sink was expected to remember that. The
    audit write did not: it masked ``redacted_summary`` and then passed ``result.citations``
    into the same :class:`~.kernel.AuditEvent` untouched, so a ticket body quoting an NRIC was
    stored verbatim in a WORM record the redactor had just cleaned, one field over, in a store
    that by design cannot be corrected afterwards.

    All THREE fields are masked, not just the snippet. ``source_id`` is content here rather than
    a bare locator, because the evidence locator is ``ticket:<subject>`` and the subject line is
    where a service desk puts the requester's address. ``title`` is engine-written today and has
    nothing to mask, and masking it is a no-op that costs nothing; deciding per field is how the
    one field nobody thought about stays raw.
    """
    return tuple(
        Citation(
            source_id=redact(citation.source_id, PII_PATTERNS),
            title=redact(citation.title, PII_PATTERNS),
            snippet=redact(citation.snippet, PII_PATTERNS),
        )
        for citation in citations
    )
