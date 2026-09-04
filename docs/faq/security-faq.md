# Security FAQ

For an AppSec reviewer sizing up this repo. It explains what the attack surface is, what is
deliberately out of scope (and why that is honest, not a gap), and where the evidence lives.
Cross-references: [`../../COMPLIANCE.md`](../../COMPLIANCE.md),
[`../practices-audit.md`](../practices-audit.md).

## What does this system actually process?

Ticket text (a subject and a free-text body, which is untrusted input written by whoever raised
the ticket) and access requests (a request reference, an opaque subject reference, a requested
role, and the entitlements the subject already holds). It produces a routing worksheet and an
eligibility worksheet. It stores no ticket system of record, holds no queryable store, and
grants no entitlement: an access verdict routes to a human and the grant happens elsewhere.

## How is identity handled? Can a caller spoof the actor?

No. Identity is resolved server-side on every route, and no request schema carries an `actor`
field. The audit actor and the review maker are both the verified `Principal`. The three families
differ honestly: `local` uses seeded dev personas through `X-Dev-Persona` (offline demo and test
only, and the adapter refuses to construct unless `local` was chosen deliberately), `gcp` verifies
the IAP-injected assertion, and `onprem` raises a placeholder that carries a status and a reason.

The one adapter that declares itself VERIFIED earns it. `adapters/gcp/identity.py` calls
`id_token.verify_token` with the configured `ITSMDESK_IAP_AUDIENCE` (three-state: unset or emptied
REFUSES, because google-auth documents `audience=None` as not verifying the audience at all, which
would accept any Google-signed token from any project), with IAP's own key set rather than
google-auth's OAuth2 default, and it checks the issuer itself because `verify_token` does not.
`tests/unit/test_iap_identity.py` runs in every gate, and `tests/unit/test_iap_crypto_matrix.py`
runs the real verifier over locally minted assertions in its own job.

## What stops the offline profile being served to the network?

An app-object loopback exposure guard, bound at module scope in `api/app.py` rather than in
`main()`, because the Dockerfile `CMD` and `make run-api` serve the app OBJECT. Its posture is
derived from the identity BINDING (whether the bound adapter can produce a verified principal
without trusting a client-written header) and from nothing else. In particular the S2S credential
`ITSMDESK_S2S_TOKEN` may never enter that decision: it authenticates a calling SERVICE and no end
user, and while it did, setting it switched the guard off for the very end-user routes it was
protecting. `tests/unit/test_serving_path_exposure.py` and
`tests/unit/test_end_user_auth_posture.py` are the standing gates. Interactive docs (`/docs`,
`/redoc`, `/openapi.json`) are ABSENT rather than guarded under the managed profile, because a
guard the profile has stood down is no guard.

Relatedly, the profile itself resolves three states at import: unset is NO CHOICE (never a silent
`local`), and an emptied or unknown value raises before the process can serve a request.

## What is the PII posture?

Redaction happens before every boundary, not once: before the audit write
(`domain/triage_service.py` and `domain/access_service.py`), before the review payload leaves the
process (`adapters/_review_payload.py`, against EVERY jurisdiction's rows because the console is a
shared sink), and before a tool result can enter a model's context (`agent/tools.py`). The API
response is deliberately NOT masked, because it goes to the caller who supplied the text; a tool
result is masked because it becomes context. The pattern set is the shared `pii-kit`, with the
jurisdictions and the row ORDER chosen per deployment in `domain/pii.py` (`SG`, `HK`, `JP`, `AU`
today, national rows first, universal email and phone rows last).
`tests/unit/test_not_falsely_green.py` proves the safety metric can go red.

## Is there a runtime guardrail for prompt injection?

No, and that is the honest answer rather than an oversight. There is no `GuardrailPort` and no
`agent-guardrail-gateway` binding; `COMPLIANCE.md` carries R1 as Partial with exactly that TODO. It matters
less today than it will tomorrow, because [there is no model in the path](../model-card.md): a
ticket body is untrusted text, but nothing interprets it as instructions. Bind the `agent-guardrail-gateway`
before any model is introduced. PII redaction is a different control and does not substitute.

## Are there secrets in the repo?

No secret value is committed. `config/settings.yaml` and `.env.example` carry variable NAMES and
non-secret defaults; `.env.secrets.example` carries placeholders. Inbound and outbound credentials
are deliberately distinct variables: `ITSMDESK_S2S_TOKEN` authenticates callers INTO this service,
while `HUMAN_REVIEW_S2S_TOKEN` and `HUMAN_REVIEW_S2S_SIGNING_KEY` are what it presents to the review console.
Practices check C10 covers this.

## What about outbound service-to-service calls?

Two exist. The review router submits an escalation to the `human-review-console` over S2S through the shared
`review-kit`, which refuses a plaintext non-loopback URL and a missing bearer at
construction, and the managed router REFUSES when no console is configured rather than swallowing
an escalation. The `model-quality-gate` promotion-gate client (`adapters/gcp/evaluation.py`) is the other, and it
refuses to run off the managed profile. Inbound service callers go through
`make_require_service_caller` from the commons.

## Is the audit trail tamper-evident?

Yes, with a stated limit and a witness for it. The offline adapter wraps the commons
`HashChainedAuditLog`: append-only, SHA-256 chained, exportable to and restorable from JSON Lines.
The chain catches an in-place edit, an interior deletion and a reorder. It CANNOT catch a
truncated tail on its own, because dropping the newest rows leaves a shorter chain that verifies
perfectly, so `audit_anchor_path` (`ITSMDESK_AUDIT_ANCHOR`) writes the chain head to a file on a
different volume under different credentials, and every append also updates it.
`tests/unit/test_audit_anchor.py` proves the detection, proves the control case goes UNDETECTED
without an anchor, and proves an append after truncation refuses rather than re-anchoring. Note
that `ITSMDESK_AUDIT_PATH` defaults to `:memory:`, which is correct for the gate and wrong for a
deployment; see [`../runbook.md`](../runbook.md).

## What is the browser boundary?

The `ui/` micro-frontend never lets the browser assert who it is. Every client-supplied actor,
tenant, role, ACL and authorization header is discarded before forwarding, identity is resolved
server-side, and the service credential is read from the server environment so it never reaches a
bundle. Framing and CORS are per-tenant allowlists that refuse a wildcard however it is written,
and an unset tenant allowlist denies. Every environment read behind that boundary resolves three
states, scanned by `ui/tests/three-state-env-reads.test.mjs`, which is the guard that exists
because a two-state read of a different variable once survived the whole gate.

## What is the supply-chain posture?

Committed `requirements-dev.lock` and `requirements-gcp.lock`, installed with `--no-deps` by
`make install`, CI and the Dockerfile, with the catalog commons pinned to 40-character commit
shas rather than movable tags; a digest-pinned non-root base image; SHA-pinned Actions;
dependabot per ecosystem; `pip-audit` over both locks and `npm audit --audit-level=high` as hard
failures. `tests/unit/test_repo_artifacts.py` asserts each of these from inside the repo, so the
posture is checked rather than described.

## What is explicitly out of scope for this repo?

The guardrail gateway (`agent-guardrail-gateway`), the governed knowledge base (`enterprise-knowledge-base`), the agent registry (`agent-registry`), the
AI-quality gate (`model-quality-gate`), the enterprise WORM audit store and trace sink (`agent-observability`), and the
human-review console (`human-review-console`). Only `human-review-console` is fully wired today; see
[features-faq.md](features-faq.md) for the boundary map and
[compliance-faq.md](compliance-faq.md) for the open rows. Also out of scope: performing the
access grant, which is your IAM system's job.
