"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..domain.models import AccessDecision, TriageResult


class TriageRequest(BaseModel):
    subject: str
    text: str


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class TriageResponse(BaseModel):
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    #: Where the escalation WENT (rule R8): the human-review-console review id, or the local queue
    #: reference. Empty exactly when ``review_routing`` is not ``routed``.
    review_ref: str = ""
    #: What happened to the hand-off: routed, failed, off or not_required. ``failed`` means the
    #: result is NOT queued for review, and the console says so.
    review_routing: Literal["routed", "failed", "off", "not_required"] = "not_required"
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(
        cls, result: TriageResult, *, review_ref: str = "", review_routing: str = "not_required"
    ) -> TriageResponse:
        return cls(
            subject=result.subject,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            review_ref=review_ref,
            review_routing=review_routing,  # type: ignore[arg-type]
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class AccessRequestModel(BaseModel):
    request_ref: str
    subject_ref: str
    requested_role: str
    current_entitlements: list[str] = []


class SoDFindingModel(BaseModel):
    code: str
    detail: str
    entitlements: list[str] = []
    citation: CitationModel | None = None


class AccessResponse(BaseModel):
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    #: Where the approval WENT (rule R8). Every access grant is consequential, so this is empty
    #: only when the hand-off did not reach the console, and ``review_routing`` says why.
    review_ref: str = ""
    #: What happened to the hand-off: routed, failed, off or not_required. ``failed`` means the
    #: decision is NOT queued for approval, and the console says so.
    review_routing: Literal["routed", "failed", "off", "not_required"] = "not_required"
    status: str = "computed"
    requested_role: str = ""
    role_risk_tier: str = ""
    #: The engine's verdict that the grant is free of segregation-of-duties conflicts. NOT
    #: permission to provision: a human still disposes, which is why ``requires_human_review`` is
    #: always true regardless of this flag.
    eligible: bool = False
    resolved_entitlements: list[str] = []
    resulting_entitlements: list[str] = []
    findings: list[SoDFindingModel] = []
    approval_chain: list[str] = []
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(
        cls, result: AccessDecision, *, review_ref: str = "", review_routing: str = "not_required"
    ) -> AccessResponse:
        return cls(
            subject=result.subject,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            review_ref=review_ref,
            review_routing=review_routing,  # type: ignore[arg-type]
            status=result.status.value,
            requested_role=result.requested_role,
            role_risk_tier=result.role_risk_tier,
            eligible=result.eligible,
            resolved_entitlements=list(result.resolved_entitlements),
            resulting_entitlements=list(result.resulting_entitlements),
            findings=[
                SoDFindingModel(
                    code=f.code,
                    detail=f.detail,
                    entitlements=list(f.entitlements),
                    citation=(
                        CitationModel(
                            source_id=f.citation.source_id,
                            title=f.citation.title,
                            snippet=f.citation.snippet,
                        )
                        if f.citation is not None
                        else None
                    ),
                )
                for f in result.findings
            ],
            approval_chain=list(result.approval_chain),
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: What the UI's model pill states before any answer: where the runtime sits and which model
    #: the bound generator calls. Both are read off the service because the browser cannot know
    #: either. Once a request is answered, the pill shows that response's ``X-Answered-By``.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
