"""Shared conversion from an escalated result to an ``review-kit`` Review payload.

Lives in the adapter layer, not the pure domain, because it depends on the kit. The subject, the
summary and EVERY field of every citation (the locator and the title, not only the snippet) are
redacted BEFORE they leave the process, using the shared ``pii-kit``, so no raw identifier
reaches Hrz7 over the wire; Hrz7 redacts again before its own audit write (defence in depth).
``maker`` and ``tenant`` are asserted here and trusted by Hrz7 because the caller is an
authenticated S2S service; per-hop on-behalf-of token exchange is the deferred next layer.
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.kernel import ReviewableResult, Severity

#: Cap the citations carried on the wire: enough for a reviewer to trace the decision without
#: copying the whole evidence set into the console.
_MAX_CITATIONS = 8

#: The console is a SHARED sink: a case filed in one market may still quote another market's
#: national id, so the payload is scrubbed against every jurisdiction's rows plus the universal
#: email/phone rows, whatever this deployment's own ``domain.pii.JURISDICTIONS`` selects.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

#: Bands that demand dual control (two approvals) rather than a single checker.
_DUAL_CONTROL = (Severity.CRITICAL,)


def _redact(text: str) -> str:
    """Mask every jurisdiction's identifiers plus email/phone, and normalise whitespace."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _kit_citations(result: ReviewableResult) -> tuple[KitCitation, ...]:
    """Mask EVERY field of every citation on the wire, and dedupe on the MASKED locator.

    Masking only the snippet was the defect: a locator is not a neutral key here, it is built out
    of whatever the case supplied. The triage evidence citation's ``source_id`` is
    ``ticket:<subject>``, and the subject line of a service-desk ticket is exactly where the
    requester's address ends up, so the console received in a citation key the identifier the
    summary beside it had masked.

    The dedupe key is the masked ``source_id`` for the same reason the outbound ``source_key``
    is built from the masked subject: two locators that differ only in the identifier they quote
    are one piece of evidence to a reviewer, and deduping on the raw value would let a retry
    deliver a different citation set than the first attempt did, which is precisely what the
    idempotency key exists to prevent.
    """
    seen: set[str] = set()
    out: list[KitCitation] = []
    for citation in result.citations:
        source_id = _redact(citation.source_id)
        if source_id in seen:
            continue
        seen.add(source_id)
        out.append(
            KitCitation(
                source_id=source_id,
                title=_redact(citation.title),
                snippet=_redact(citation.snippet),
            )
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def result_to_review(
    result: ReviewableResult, *, maker: str, tenant: str = "", action: str = "review"
) -> Review:
    """Build the review a producer submits to Hrz7 when a result escalates.

    ``action`` (``triage`` / ``access``) distinguishes which vertical escalated, so the console
    and the idempotency key separate two producers that may both file on the same subject.

    The subject is redacted ONCE and reused for every field that carries it outward, the
    ``case_ref`` and the ``source_key`` included: those are part of the outbound payload, so the
    redact-before-anything rule covers them exactly as it covers the visible summary. A triage
    subject is usually a company reference with nothing to mask, but an access ``subject_ref`` may
    carry a personal identifier, and a raw one must never reach the shared console even in a key.
    """
    safe_subject = _redact(result.subject)
    return Review(
        action=f"itsm_servicedesk_triage:{action}",
        subject=safe_subject,
        maker=maker,
        tenant=tenant,
        summary=_redact(result.summary),
        severity=result.severity.value,
        required_approvals=2 if result.severity in _DUAL_CONTROL else 1,
        sod_group=f"itsm_servicedesk_triage-{action}-maker-checker",
        case_ref=safe_subject,
        # Producer-owned, tenant-scoped key so a retried delivery is idempotent at the console.
        source_key=f"H3:{action}:{safe_subject}:{result.severity.value}",
        citations=_kit_citations(result),
    )
