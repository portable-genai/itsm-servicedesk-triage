# Compliance FAQ

For compliance, operational-risk and model-risk teams assessing this repo's posture.
Cross-references: [`../../COMPLIANCE.md`](../../COMPLIANCE.md) (every principle P-01 to P-13 and
every rule R1 to R8 mapped to a control and an evidence file, plus the adopter-owned regulator
crosswalk), [`../../SPEC.md`](../../SPEC.md), [`../practices-audit.md`](../practices-audit.md).

### Is this system deciding anything autonomously?

No. It is decision support with a mandatory human disposition on anything consequential. **Every
access decision routes to a human by construction**: `requires_human_review` is always set,
`decision` is always `ESCALATED`, and nothing is provisioned in-process, whatever the eligibility
arithmetic says. On the triage side a `HIGH` or `CRITICAL` band escalates and the rest are routed
to a queue a human works. `CRITICAL` demands two approvals.

Crucially the escalation is not a per-repo boolean: setting the flag and calling
`ReviewRouterPort.route` is one act, performed by the API, the CLI and the agent tool in the same
call that produced the result (rule R8), and `tests/unit/test_review_routing.py` asserts the
routing rather than the flag. The console is the sibling `human-review-console` system; the managed router
REFUSES when no console is configured rather than swallowing an escalation.

### Is a model involved in any decision?

No model is involved in anything, today. There is no generation or LLM port bound in any profile,
despite the README calling the agent "model-advised"; the discrepancy and the boundary a model
would have to respect are recorded in [`../model-card.md`](../model-card.md). Every consequential
output comes from a deterministic, replayable stdlib engine reading a versioned policy pack, so a
reviewer can recompute any verdict from the same inputs and the same pack. That also means there
is currently no model risk to document, no prompt to version, and nothing for a model-validation
function to test beyond the engines themselves.

### How is the work auditable and explainable?

Every result carries a `Citation` back to the pack clause that decided it: the taxonomy clause
for a route, the role clause and the conflict clause for an SoD finding, plus an evidence excerpt
of the ticket text. Every interaction writes an already-redacted `AuditEvent` whose actor is the
verified principal and never the request body. The offline audit log is append-only and SHA-256
hash-chained with an EXTERNAL head anchor, because a chain alone cannot detect a truncated tail;
`tests/unit/test_audit_anchor.py` proves the detection and proves the control case goes undetected
without the anchor. In the managed profile the trail lands in a locked Cloud Logging WORM bucket
(`infra/terraform/logging_worm.tf`, retention floor 180 days, CMEK-encrypted, and the lock is
IRREVERSIBLE once applied). The enterprise WORM and trace sink is the sibling `agent-observability` system, and
binding the audit half to it is still open (rule R2).

### How is personal data minimised?

Redaction happens before every boundary, not once: before the audit write, before the review
payload leaves the process (against every jurisdiction's rows, because the console is a shared
sink), and before a tool result can enter a model's context. The jurisdiction list is a
deployment choice in `domain/pii.py`. The safety metric is scored two ways in the eval, at a
`pii_safety >= 0.99` threshold, and `tests/unit/test_not_falsely_green.py` proves that metric can
go red. The runtime guardrail and output filtering themselves are the sibling `agent-guardrail-gateway`,
which is NOT bound here yet (rule R1).

### Is data residency enforced, or only documented?

Both halves exist and both are worth checking separately. In the application the region is chosen
once (`asia-southeast1`), carried by `config/settings.yaml`, reported by `/healthz` and printed on
the agent card, so a drifting deployment is visible. At deploy time `infra/terraform/` enforces it:
`var.region` is validated against `var.allowed_regions` at plan time, `org_policy.tf` applies the
`gcp.resourceLocations` allowlist restricted to the region's location group (plus disabling
service-account key creation and requiring uniform bucket-level access), `kms.tf` creates a
REGIONAL CMEK key ring with 90-day rotation and per-service-agent bindings, and `vpc_sc.tf` stands
up a dry-run-first VPC Service Controls perimeter.

The honest caveat: the org-policy and perimeter layers are gated on `var.enable_org_policies` and
`var.enable_vpc_sc`, and the documented quick-evaluation posture turns both off. There are
executable assertions of these claims in `infra/terraform/production_edge.tftest.hcl`, but no
target in this repo's offline gate runs `terraform test`, so they are not regression-guarded by a
build. `COMPLIANCE.md` keeps P-03 at Partial for exactly that reason.

### What is the model-risk and promotion story?

`eval/run_eval.py --mode smoke` runs in the offline gate on every change and scores five metrics
against the datasets' own hand-labelled `expected_*` oracles, never against the pipeline's own
verdict: `decision_accuracy` and `routing_accuracy` at 0.80, `pii_safety` at 0.99, and
`sod_precision` and `sod_recall` at 1.00 (a segregation-of-duties engine that misses a toxic
combination has failed at its only job). Every metric is proven ABLE TO GO RED on a degraded
input before its green is trusted. `--mode gate` delegates the promotion verdict to the sibling
`model-quality-gate` authority and refuses to run off the managed profile, under bundle name
`itsm-servicedesk-triage`. Registering that bundle and its thresholds with `model-quality-gate` is still open
(P-08 and R5).

### Which rows are still open?

Read `COMPLIANCE.md` for the authoritative list; the summary is that P-02 (ports and adapters),
P-04 (data minimisation), P-06 (maker-checker), P-07 (auditability), P-12 (reversibility) and R8
(routed escalations) are Covered with a test behind each; P-01, P-03, P-08, P-09, R1, R2, R4, R5
and tenant isolation are Partial with the missing half named; P-05 (grounding), P-10 (resilience,
including the CPS 230 recovery objectives), P-11 (cost and latency) and R6 (`architecture-validator` intake) are
explicit `TODO (repo owner)` rows. Several of those are open precisely because there is no model
and no retrieval yet, and claiming them would be worse than owing them. The practices audit
(`docs/practices-audit.md`) carries the same discipline per check.

### Which regulators does this map to?

`COMPLIANCE.md` maps to the catalog's own principles and rules, aligned to MAS TRM, APRA CPS 234
and CPS 230, HKMA and PDPA-class regimes. The mapping from those to a specific regulation, and the
judgement that a control is SUFFICIENT for it, is deliberately **adopter-owned**: it depends on
your risk appetite, your regulator, your licence conditions and your existing control library. No
row in this repo should be quoted as regulatory assurance. What an adopter adds in their own
control library is listed at the end of `COMPLIANCE.md`: the crosswalk to their control ids, the
risk acceptance for every Partial or TODO row at go-live, the second-line review of the
deterministic policy in `domain/` and the packs (bank-owned logic, not a vendor default to be
inherited unexamined), and the retention schedule and legal basis for the audit trail.

### Can we run it against real data today?

Not without your own legal, security and model-risk sign-off. Every fixture, demo case and golden
case is obviously fictional (parties suffixed FICTIONAL, `.example` domains, RFC 5737 and RFC 3849
literals), and the shipped taxonomy and segregation-of-duties matrix are illustrative and
synthetic. The adoption checklist in [`../ADOPTING.md`](../ADOPTING.md) lists the steps that must
precede any live use.
