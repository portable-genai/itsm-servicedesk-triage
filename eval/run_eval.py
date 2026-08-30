#!/usr/bin/env python3
"""Evaluation gate for ITSM Service Desk Agent (H3).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change: it drives the real
  ``TriageService`` and ``AccessEngine`` against golden sets with SDK-free local adapters and
  scores five metrics, each against the dataset's OWN hand-labelled ``expected_*`` oracle, never
  against the pipeline's own verdict.
* **gate** - the promotion verdict from the shared Hrz4 authority (requires the ``gcp``
  profile), via ``agent_eval_kit.PromotionGateClient``.

Every smoke metric is proven ABLE TO GO RED before the real scores are trusted (a metric that
cannot fail proves nothing): ``_prove_metrics_can_go_red`` runs ``agent_eval_kit.assert_can_go_red``
on a clean / degraded pair per metric, including the plan's own red proof for the SoD engine,
injecting a wildcard conflict that must drop precision below its bar. Exit is ``0`` iff every
metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_eval_kit import (
    EvalMetricResult,
    EvalReport,
    PromotionGateClient,
    assert_can_go_red,
    eval_main,
)
from pii_kit import pack_leak
from pii_kit import redact as pii_redact

from itsm_servicedesk_triage.adapters.local.audit import (
    LocalAuditAdapter,
)
from itsm_servicedesk_triage.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from itsm_servicedesk_triage.config import (
    Settings,
)
from itsm_servicedesk_triage.domain.access_engine import (
    AccessEngine,
)
from itsm_servicedesk_triage.domain.models import (
    AccessRequest,
    TriageInput,
)
from itsm_servicedesk_triage.domain.packs import AccessPolicy, SoDConflict
from itsm_servicedesk_triage.domain.pii import (
    PII_PATTERNS,
)
from itsm_servicedesk_triage.domain.triage_service import (
    TriageService,
)
from itsm_servicedesk_triage.packs import default_triage_engine, load_access_policy

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"
DEFAULT_ACCESS_DATASET = _REPO_ROOT / "eval" / "datasets" / "access_cases.jsonl"

THRESHOLDS: dict[str, float] = {
    "decision_accuracy": 0.80,
    "routing_accuracy": 0.80,
    "pii_safety": 0.99,
    "sod_precision": 1.00,
    "sod_recall": 1.00,
}
#: The registered Hrz4 metric bundle for this vertical (Hrz4 owns the metrics + thresholds).
_BUNDLE = "itsm-servicedesk-triage"

#: A checksum-valid synthetic NRIC, and a raw summary carrying it, for the pii_safety red proof:
#: redaction ON is the clean case, redaction OFF (the raw string) is the mutant to catch.
_PLANTED_NRIC = "S1234567D"
_RAW_PII = f"Gamma LLP: triaged high :: urgent breach, NRIC {_PLANTED_NRIC} on file"


def _load(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


# --------------------------------------------------------------------------------------------- #
# Pure metric score functions. Each takes what it scores and returns a value in [0, 1], so the
# SAME function serves both the real run and the can-go-red proof (clean input passes, degraded
# input fails). None reads the pipeline's own verdict: the label always comes from the dataset.
# --------------------------------------------------------------------------------------------- #


def _accuracy(pairs: Sequence[tuple[str, str]]) -> float:
    """Mean exact-match of (predicted, expected). Empty scores 0.0, never a vacuous pass."""
    if not pairs:
        return 0.0
    return round(sum(1.0 if pred == exp else 0.0 for pred, exp in pairs) / len(pairs), 4)


def _pii_row(snippet: str) -> dict[str, Any]:
    """One audit row shaped like the ones the pipeline writes: masked summary plus citations.

    The row, not a bare string, is what the pii_safety proof is built on. The failure this metric
    had was never in the comparison; it was in WHICH FIELDS the comparison was handed, and a proof
    over a lone string re-passes the moment a sink puts the identifier in a field nobody reads.
    """
    return {
        "redacted_summary": pii_redact(_RAW_PII, PII_PATTERNS),
        "citations": [
            {
                "source_id": "ticket:Gamma LLP (FICTIONAL)",
                "title": "Ticket description",
                "snippet": snippet,
            }
        ],
    }


def audit_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every CONTENT-bearing field of each persisted audit row, citations included.

    ``redacted_summary`` is one field of several the WORM record keeps, and scoring it alone is
    how a metric ends up certifying the leak it exists to catch: the summary is masked, the
    citations stored beside it in the same row are not, and the identifier survives in a record
    the metric has just called clean. A citation's ``source_id`` is content here, not a bare
    locator, because a locator is built out of the identifiers the case supplied.

    ``actor`` is deliberately absent. It is the VERIFIED principal and an address by design, so a
    blanket scan over a whole row could never go green, and a metric that can never go green is a
    metric somebody switches off. Scanning the content fields is what makes this both sound and
    reachable.

    Named and module-level rather than inline in :func:`run_smoke` so the falsification proof in
    ``tests/unit/test_not_falsely_green.py`` can drive the SHIPPED pair instead of a lookalike.
    """
    out: list[str] = []
    for row in rows:
        out.append(str(row.get("redacted_summary", "")))
        out.append(json.dumps(row.get("citations", []), sort_keys=True, default=str))
    return out


def pii_safety(surfaces: Sequence[str], planted: Sequence[str]) -> float:
    """1.0 unless a raw identifier survived into an audit record, by pack row OR by literal.

    The pack scan uses the same rows the redactor masks with, so it catches PII the pipeline
    re-introduced after redaction; the planted-literal scan is an independent oracle that still
    fires when a pack row is narrowed or broken (the two-part scorer lesson from the C4 rollout).
    """
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in surfaces)
    literal_leaked = any(token in text for token in planted for text in surfaces)
    return 0.0 if (pack_leaked or literal_leaked) else 1.0


def _sod_counts(policy: AccessPolicy, cases: Sequence[dict[str, Any]]) -> tuple[int, int, int]:
    """Return (true positives, false positives, false negatives) of the BLOCK decision.

    A grant the engine declares ineligible is a positive; the oracle's ``expected_eligible`` says
    whether it truly should have been blocked. Nothing here reads the engine's own eligibility as
    truth: the label is the dataset's.
    """
    engine = AccessEngine(policy)
    tp = fp = fn = 0
    for case in cases:
        decision = engine.assess(
            AccessRequest(
                request_ref=str(case["request_ref"]),
                subject_ref=str(case["subject_ref"]),
                requested_role=str(case["requested_role"]),
                current_entitlements=tuple(case.get("current_entitlements", [])),
            )
        )
        blocked = not decision.eligible
        truly_ineligible = not bool(case["expected_eligible"])
        if blocked and truly_ineligible:
            tp += 1
        elif blocked and not truly_ineligible:
            fp += 1
        elif not blocked and truly_ineligible:
            fn += 1
    return tp, fp, fn


def _sod_precision(policy: AccessPolicy, cases: Sequence[dict[str, Any]]) -> float:
    """Of the grants the engine BLOCKED, the fraction that were truly ineligible."""
    tp, fp, _ = _sod_counts(policy, cases)
    denom = tp + fp
    return round(tp / denom, 4) if denom else 1.0


def _sod_recall(policy: AccessPolicy, cases: Sequence[dict[str, Any]]) -> float:
    """Of the truly-ineligible grants, the fraction the engine BLOCKED."""
    tp, _, fn = _sod_counts(policy, cases)
    denom = tp + fn
    return round(tp / denom, 4) if denom else 1.0


def _wildcard_policy(policy: AccessPolicy) -> AccessPolicy:
    """The policy with a WILDCARD conflict added: a toxic pair both held by a clean golden role.

    ``payments_approver`` legitimately holds both ``payment.view`` and ``payment.approve``, so a
    conflict on that pair blocks a grant the oracle marks eligible: a false positive that must
    drive sod_precision below 1.0. This is the plan's own red proof for the SoD engine.
    """
    wildcard = SoDConflict(
        conflict_id="wildcard-test-only",
        entitlements=frozenset({"payment.view", "payment.approve"}),
        detail="TEST-ONLY wildcard conflict that also blocks a clean grant",
        source_id=policy.source_id,
        source_title=policy.source_title,
        citation_clause="WILD",
    )
    return dataclasses.replace(policy, conflicts=(*policy.conflicts, wildcard))


def _prove_metrics_can_go_red(access_cases: Sequence[dict[str, Any]]) -> None:
    """Prove every smoke metric can FAIL on a degraded input before its green is trusted.

    A metric that cannot go red is not a metric. The clean/degraded pairs are constructed here,
    not scored from the pipeline: correct-vs-wrong labels for the accuracy metrics, redaction
    on-vs-off for pii_safety, and the shipped-vs-wildcard policy for the SoD metrics.
    """
    for metric, thr in (
        ("decision_accuracy", THRESHOLDS["decision_accuracy"]),
        ("routing_accuracy", THRESHOLDS["routing_accuracy"]),
    ):
        assert_can_go_red(
            _accuracy,
            green=[("match", "match")],
            red=[("wrong", "expected")],
            threshold=thr,
            metric=metric,
        )

    def _rows_score(rows: Sequence[Mapping[str, Any]]) -> float:
        return pii_safety(audit_surfaces(rows), [_PLANTED_NRIC])

    # The mutant is the SHAPE of the C3 defect: the summary stays masked and the citation stored
    # in the same row keeps the raw identifier. Scored through the shipped surface extractor, so
    # narrowing the extractor again fails this proof instead of quietly passing it.
    assert_can_go_red(
        _rows_score,
        green=[_pii_row(pii_redact(_RAW_PII, PII_PATTERNS))],
        red=[_pii_row(_RAW_PII)],
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
    policy = load_access_policy()
    wildcard = _wildcard_policy(policy)
    empty = dataclasses.replace(policy, conflicts=())

    def _precision(candidate: AccessPolicy) -> float:
        return _sod_precision(candidate, access_cases)

    def _recall(candidate: AccessPolicy) -> float:
        return _sod_recall(candidate, access_cases)

    # Precision goes red when a wildcard conflict over-blocks a clean grant (a false positive).
    assert_can_go_red(
        _precision,
        green=policy,
        red=wildcard,
        threshold=THRESHOLDS["sod_precision"],
        metric="sod_precision",
    )
    # Recall goes red when the conflict matrix is emptied and the toxic combinations sail through.
    assert_can_go_red(
        _recall,
        green=policy,
        red=empty,
        threshold=THRESHOLDS["sod_recall"],
        metric="sod_recall",
    )


def run_smoke(dataset: Path) -> EvalReport:
    triage_cases = _load(dataset)
    access_cases = _load(DEFAULT_ACCESS_DATASET)

    # Refuse to trust any green until every metric is shown able to go red on a degraded input.
    _prove_metrics_can_go_red(access_cases)

    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    service = TriageService(audit, default_triage_engine(), tracer=LocalNoopTracerAdapter(settings))

    severity_pairs: list[tuple[str, str]] = []
    queue_pairs: list[tuple[str, str]] = []
    for case in triage_cases:
        result = service.triage(
            TriageInput(subject=str(case["subject"]), text=str(case["text"])), actor="eval-bot"
        )
        severity_pairs.append((result.severity.value, str(case["expected_severity"])))
        queue_pairs.append((result.queue, str(case["expected_queue"])))

    # pii_safety: no raw identifier may survive into any audit record.
    surfaces = audit_surfaces(audit.log.read_all())
    planted = [str(case["planted"]) for case in triage_cases if case.get("planted")]
    safety = pii_safety(surfaces, planted)

    policy = load_access_policy()

    results = (
        EvalMetricResult.scored(
            "decision_accuracy", _accuracy(severity_pairs), THRESHOLDS["decision_accuracy"]
        ),
        EvalMetricResult.scored(
            "routing_accuracy", _accuracy(queue_pairs), THRESHOLDS["routing_accuracy"]
        ),
        EvalMetricResult.scored("pii_safety", safety, THRESHOLDS["pii_safety"]),
        EvalMetricResult.scored(
            "sod_precision", _sod_precision(policy, access_cases), THRESHOLDS["sod_precision"]
        ),
        EvalMetricResult.scored(
            "sod_recall", _sod_recall(policy, access_cases), THRESHOLDS["sod_recall"]
        ),
    )
    return EvalReport(
        dataset=str(dataset), results=results, n_examples=len(triage_cases) + len(access_cases)
    )


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"ITSMDESK_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("ITSMDESK_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / Hrz4 evaluation gate for H3.",
        )
    )
