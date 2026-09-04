# Adopting this repo as your base

This repository (H3, the ITSM Service Desk Agent) is a **common base** that a bank or other
regulated institution forks to build its own IT service-desk agent. It ships a reusable
hexagonal core (a pure-stdlib domain, typed ports, three swappable adapter profiles, a green
offline gate) plus two fully worked verticals you can keep, retune, or replace: **deterministic
ticket triage** (a ticket in, a category, priority, severity and queue out) and a
**segregation-of-duties access check** (an access request in, an entitlement union, an SoD
verdict and an approval chain out). Neither vertical provisions anything: the access decision is
consequential by construction, so it always routes to a human and nothing is granted in-process.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and the three
> profiles), [`CONTRIBUTING.md`](../CONTRIBUTING.md) (the five homes of a port, and the
> adapter touch list), [`COMPLIANCE.md`](../COMPLIANCE.md) (every principle and rule mapped to
> a control), [`model-card.md`](model-card.md) (the model boundary, which today records that
> there is no model), and the [`faq/`](faq/README.md) directory.

---

## 1. What you keep vs what you rewrite

The domain is split so the boundary is a physical module split with an enforced dependency
direction (practices-audit check A7). `domain/kernel.py` holds the vertical-neutral machinery and
imports nothing from this vertical; `domain/models.py` holds only the H3 artifacts and imports
`kernel`, never the reverse.

| Layer | Where | For a new vertical |
|---|---|---|
| **Kernel** (vertical-neutral) | `domain/kernel.py`: `Severity`, `Decision`, `VerdictStatus`, `Citation`, the `ReviewableResult` protocol, `AuditEvent`, `utcnow`. Plus every Protocol in `ports/`, the `Container` wiring in `config.py`, and the shared review converter `adapters/_review_payload.py` | keep untouched |
| **Policy** (your numbers, as data) | The two packs under `config/packs/`: the triage categories, keyword lists, `priority_severity` band map and defaults in [`triage/taxonomy.yaml`](../config/packs/triage/taxonomy.yaml), and the roles, entitlements, risk tiers, `sod_conflicts` and `approval_chains` in [`access/policy.yaml`](../config/packs/access/policy.yaml). Also `JURISDICTIONS` in `domain/pii.py` and `THRESHOLDS` in `eval/run_eval.py` | change deliberately (section 4) |
| **Vertical** (the artifacts) | The request and result types in `domain/models.py` (`TicketSignals`, `TriageInput`, `TriageResult`, `AccessRequest`, `SoDFinding`, `AccessDecision`), the two engines `domain/triage_engine.py` and `domain/access_engine.py` with their services, the fixtures in `tests/fixtures/sample_cases.py`, the eval golden sets in `eval/datasets/`, and the UI views | rewrite or reseed |

If your product is another **deterministic worksheet plus human disposition** service (an
approval gate, an entitlement review, a request router), the hexagon, the three profiles, the
anchored audit chain, the eval gate and the `human-review-console` review routing transfer directly. You replace
the two packs and `domain/models.py`, and retune the thresholds.

Two engine constants are NOT in a pack today, and they are worth knowing about before you fork:
`_ESCALATING_SEVERITIES` in `domain/triage_engine.py` (which bands escalate: `HIGH` and
`CRITICAL`) and `_TIER_SEVERITY` in `domain/access_engine.py` (role risk tier to review
severity). Everything else the engines decide from comes out of the packs.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): the kernel types, `ports/`, `tests/contract/`, the eval
  harness mechanics (`eval/run_eval.py` structure), the CI workflows, the hexagon wiring
  (`config.py` `Container`), the review converter (`adapters/_review_payload.py`) and the
  `scripts/` demo surface.
- **Adopter-owned** (yours; expect to edit): **the two policy packs** under `config/packs/`, the
  `config/settings.yaml` values, `domain/pii.py` `JURISDICTIONS`, `adapters/onprem/*`, UI theming
  and branding, the golden eval datasets, and the jurisdiction rows in `COMPLIANCE.md`.

The packs are the prime adopter-owned surface, and they are designed for it. `domain/packs.py`
loads them strictly: an unknown field, a missing required field, a priority outside `p1..p4`, a
duplicate `category_id` or `role_id`, an SoD conflict naming an entitlement no role grants, or a
`priority_severity` map missing a band all REFUSE at load rather than being ignored. A pack that
silently dropped a field it did not recognise would be a policy nobody reviewed, so your pack
fails loudly on the first load instead of routing on half a taxonomy. Exactly one file is
expected under each of `config/packs/triage/` and `config/packs/access/`.

Track upstream via git tags; rebase your adopter-owned changes onto each release rather than
merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the python package (`itsm_servicedesk_triage`), the
console-script name (`itsm_servicedesk_triage`, which in this repo equals the package name), the
`ITSMDESK` env-var prefix, the Terraform `name_prefix` stem (`h3-svc`) and the distribution / git
id (`itsm-servicedesk-triage`) across the tree in one simultaneous pass. Preview first, then
apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_servicedesk --cli acme-desk \
    --env-prefix ACME --resource acme-desk --dry-run

# Apply, sweeping Markdown prose as well:
python scripts/rename_fork.py --package acme_servicedesk --cli acme-desk \
    --env-prefix ACME --resource acme-desk --include-docs --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

`make gate` is this repo's gate command (`ruff check` plus `ruff format --check` plus `mypy src`
plus `pytest -m 'not integration'` plus the eval smoke run). `--dist` defaults to the package
name with underscores replaced by hyphens; pass it explicitly if your git id follows a different
convention. Omit `--include-docs` to leave Markdown prose alone. The script deliberately does NOT
touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region and residency.** The region is chosen once and shared: `region:` in
   `config/settings.yaml` (`${GCP_REGION:-asia-southeast1}`), and in Terraform both `var.region`
   and `var.allowed_regions`, which are validated against each other at plan time so an
   off-allowlist region fails `terraform plan` rather than reaching an apply. Set both to your
   in-country region. See [`runbook.md`](runbook.md).
2. **Identity and your IdP.** This repo owns no login flow. `local` uses seeded dev personas
   through the `X-Dev-Persona` header (offline demo and test only, and the adapter refuses to
   construct unless `local` was chosen deliberately); `gcp` verifies the IAP-injected assertion
   against `ITSMDESK_IAP_AUDIENCE`, IAP's own key set and the expected issuer; `onprem` raises a
   placeholder that carries a status and a reason. Configure IAP on the deployed service and set
   the audience, or implement the `onprem` identity adapter against your IdP. An unset or emptied
   audience refuses every caller rather than verifying without one.
3. **The triage taxonomy.** The shipped taxonomy is illustrative and synthetic: six categories
   (`fraud_or_sanctions`, `security_incident`, `major_outage`, `access_request`, `billing_query`,
   `hardware`) matched first-category-wins in the order listed, a `priority_severity` map from
   `p1..p4` to `critical / high / medium / low`, and a default category and queue for a ticket
   that matches nothing. Severity is a pure function of the matched category's band, so no
   keyword modifier can lift a ticket above the band its category declares. Replace the whole
   file with your own reviewed taxonomy, and remember that the ORDER of the categories is
   policy, not formatting.
4. **The segregation-of-duties matrix.** Also illustrative and synthetic: seven roles with their
   entitlements and risk tiers, four toxic combinations (maker plus checker on payments, vendor
   creation plus payment creation, ledger posting plus payment approval, IAM self-grant plus
   payment approval), and four approval chains keyed by risk tier. Auto-approval is deliberately
   not a member of any chain. This is bank-owned logic and needs your second line's review, not
   a vendor default inherited unexamined; the engine reasons over the UNION of the requested
   role's entitlements and what the subject already holds, so a conflict that only forms in
   combination is still caught.
5. **Reference data is fictional.** Every fixture (`tests/fixtures/sample_cases.py`), every demo
   case in `scripts/demo.py` and every golden case announces itself as synthetic (parties
   suffixed FICTIONAL, `.example` domains, RFC 5737 and RFC 3849 literals). The one national id
   in the fixtures exists so a redaction check has an independent literal to look for. **Do not
   run against real tickets or real entitlement data without your own security and model-risk
   sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/golden_cases.jsonl` and
   `eval/datasets/access_cases.jsonl` for your taxonomy and your matrix, and revisit `THRESHOLDS`
   in `eval/run_eval.py` (`decision_accuracy` and `routing_accuracy` at 0.80, `pii_safety` at
   0.99, `sod_precision` and `sod_recall` at 1.00). A fork inherits a green gate that measures
   the WRONG taxonomy until you do. The harness structure and the can-go-red proof are generic;
   the golden cases are yours.
7. **PII jurisdictions.** `JURISDICTIONS` in `domain/pii.py` selects and ORDERS the pattern rows
   from the shared `pii-kit` (`SG`, `HK`, `JP`, `AU` today, national rows first and the
   universal email and phone rows last). Set the jurisdictions you actually serve.
8. **Audit durability.** `ITSMDESK_AUDIT_PATH` defaults to `:memory:`, which is right for the
   gate and wrong for a deployment. Point it at a durable path AND set `ITSMDESK_AUDIT_ANCHOR` to
   a file on a different volume under different credentials: the hash chain catches an edit, a
   deletion or a reorder, and only the external anchor catches a truncated tail.
9. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001,
   healthcheck on `/healthz`) and `infra/terraform/` before you expose anything: `var.region` and
   `var.allowed_regions`, `var.enable_org_policies`, `var.enable_vpc_sc` with `var.vpc_sc_enforce`
   (apply in dry run first, watch the denials, then enforce), `var.retention_days` and
   `var.worm_locked` (the WORM lock is IRREVERSIBLE), and `var.production_edge_enabled` with the
   IAP variables. See [`runbook.md`](runbook.md) and
   [`onprem-migration.md`](onprem-migration.md).

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it *touches* are
owned by sibling platform services. Integrate them rather than rebuilding them, and be clear
about which are already wired here and which are not: the honest per-rule status is the R1 to R8
table in [`COMPLIANCE.md`](../COMPLIANCE.md), and this is its summary.

| Concern | Owned by | Wired here today? |
|---|---|---|
| Human review and maker-checker console | `human-review-console` | **Yes.** `ports/review_router.py` with an adapter in every profile, on the shared `review-kit` (a hard dependency, not an extra). `review_url` comes from `HUMAN_REVIEW_URL`; the managed router REFUSES when no console is configured rather than swallowing an escalation (rule R8, Covered). |
| AI-quality and promotion gate | `model-quality-gate` | **Client half only.** `adapters/gcp/evaluation.py` asks the `model-quality-gate` authority through `agent-eval-kit`, under bundle name `itsm-servicedesk-triage` at `ITSMDESK_QUALITY_URL`, and refuses to run off the managed profile. The bundle and its thresholds are NOT registered with `model-quality-gate` yet (P-08 / R5). |
| Observability, tracing and enterprise WORM audit | `agent-observability` | **Tracing half only.** The tracer port is bound in every profile and the managed adapter exports OTLP to the `agent-observability` collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The audit trail is still this process's own hash-chained store; no observability client is bound to the shared sink (R2). |
| Agent registry, versioning, entitlements | `agent-registry` | **No.** The agent publishes an A2A card at `/.well-known/agent-card.json` built from the same tool table the runtime binds, but nothing registers it and the agent takes no identity or entitlements from `agent-registry` (R4). |
| Runtime guardrail: prompt-injection defence, output filtering | `agent-guardrail-gateway` | **No.** There is no `GuardrailPort`. PII redaction is in-repo through the shared `pii-kit`, which is not the same control. Bind the guardrail before any untrusted ticket text reaches a model (R1). |
| Governed RAG and knowledge base | `enterprise-knowledge-base` | **No, and not needed today.** Nothing retrieves; the engines compute from the packs. A fork that adds a KB article suggestion must add a `KnowledgeBasePort` bound to `enterprise-knowledge-base` and make empty retrieval a hard error (R3, P-05). |
| Project intake validation | `architecture-validator` | **No.** An intake action rather than a code control; record the validation reference in `COMPLIANCE.md` when the project passes (R6). |

Two boundaries worth stating plainly, because they are where a fork is most tempted to overreach:

- **This repo does not provision access.** The access engine produces an eligibility verdict, the
  entitlement union a reviewer would be approving, the findings and the approval chain. Granting
  the entitlement is your IAM or joiner-mover-leaver system's job, downstream of the human
  disposition `human-review-console` records.
- **This repo does not run a model.** See [`model-card.md`](model-card.md). Adding one is a real
  change with real prerequisites, not a configuration flip.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make install` and `make gate` green.
- [ ] Set the region in `config/settings.yaml` and BOTH `var.region` and `var.allowed_regions` in tfvars to your in-country region.
- [ ] Wired your IdP (IAP audience on the deployed service, or the `onprem` identity adapter).
- [ ] Replaced `config/packs/triage/taxonomy.yaml` with your own reviewed taxonomy, category order included.
- [ ] Replaced `config/packs/access/policy.yaml` with your role catalog, SoD matrix and approval chains, and had second line review them.
- [ ] Set `JURISDICTIONS` in `domain/pii.py` to the jurisdictions you serve.
- [ ] Replaced every synthetic fixture and demo case.
- [ ] Rebuilt both eval golden sets and revisited `THRESHOLDS`.
- [ ] Pointed `ITSMDESK_AUDIT_PATH` at durable storage and set `ITSMDESK_AUDIT_ANCHOR` on a different volume.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform toggles, WORM retention and lock, bind address).
- [ ] Wired your `human-review-console` endpoint and decided which other sibling services you integrate vs leave open.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
