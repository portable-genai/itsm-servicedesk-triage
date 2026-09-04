# Features FAQ

For product, service-management and delivery teams: what this agent produces, what is
deterministic, what it deliberately will not do, and where its responsibilities **stop** and a
sibling catalog system takes over. Cross-references: [`../../README.md`](../../README.md),
[`../../DEMO.md`](../../DEMO.md), [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).

### What does H3 actually produce?

Two cited worksheets, from two verticals that share one domain, one audit trail and one
escalation path.

**Ticket triage.** An inbound ticket (a subject, the free-text body, and optionally an advisory
classification) in; a routing worksheet out: the category, the priority band, the severity, the
affected service and the QUEUE, plus `model_agreed`, a `rule_id` and two citations (the taxonomy
clause that decided the route, and an evidence excerpt of the ticket text). Escalation is a
consequence of the band: `HIGH` and `CRITICAL` route to a human, the rest do not.

**Access provisioning check.** An access request (a request reference, an opaque subject
reference, the requested role, and the entitlements the subject already holds) in; an eligibility
worksheet out: the role's risk tier, the resolved entitlements, the union the subject WOULD hold,
an eligibility verdict, every segregation-of-duties finding with the exact toxic combination that
triggered it, and the approval chain for the risk tier.

### Is any of it done by a model?

No. **There is no model in this system's path today**, despite the README tagline calling the
agent "model-advised". No generation, narration or LLM port exists, is bound or is called in any
profile. The severity band, the queue, the SoD verdict and the approval chain are all computed by
pure-stdlib engines (`domain/triage_engine.py` and `domain/access_engine.py`) from two policy
packs. The place a model's opinion WOULD land is documented (`TicketSignals` in
`domain/models.py`, which the engine reads only to detect disagreement), and the full boundary
plus the controls a model would first require are in [`../model-card.md`](../model-card.md).

### Does it provision access, or close tickets?

No, and this is the sharpest boundary in the repo. **Every grant is consequential by
construction**, so an access decision always sets `requires_human_review`, always reports
`ESCALATED`, and is always routed to the `human-review-console` in the same call that produced
it (rule R8). Nothing is provisioned in-process. The engine decides eligibility and names the
approval chain; a human disposes; your IAM or joiner-mover-leaver system performs the grant
downstream of that disposition. Triage likewise routes a ticket to a queue and never resolves it.

### What happens when the engine does not know?

It refuses to guess. `VerdictStatus.NEEDS_INFO` means the engine reached no verdict (an unknown
role, an unmapped fact), and the result routes to a human by construction rather than being
auto-decided. On the triage side a ticket matching no category lands in the declared default
category and queue, which is a real queue a human works rather than a silent drop, and the
result still carries the status so a persistent miss is visible.

### How many ways can I call it, and do they agree?

Five, and they agree because they share the domain service rather than reimplementing it: the
FastAPI app (`POST /v1/triage`, `POST /v1/access`, plus `/healthz`, the A2A card at
`/.well-known/agent-card.json` and the ops routes), the argparse CLI (`triage` and `access`
subcommands), the agent tools (`triage_case`, `assess_access`, `verify_audit_trail`, advertised
on the agent card), the embeddable Next.js micro-frontend in `ui/`, and the eval harness. Each of
them routes an escalated result to human review in the same call that produced it, so rule R8
does not hold on four surfaces out of five.

### Which capabilities does this repo own vs integrate from the catalog?

It **owns** the two deterministic engines, the policy packs, the audit chain and the surfaces.
It **integrates**, or still needs to integrate, the cross-cutting concerns owned by sibling
platform systems. Do not rebuild these in a fork:

| Concern | Owned by | This repo's role today |
|---|---|---|
| Human review and maker-checker console | `human-review-console` | **Wired.** Every escalation is routed to it through the shared `review-kit`, redacted before the wire, with the verified principal as maker (rule R8). |
| AI-quality and promotion gate | `model-quality-gate` | **Client half wired.** `eval/run_eval.py --mode gate` asks the authority and refuses to run off the managed profile; the metric bundle is not registered with `model-quality-gate` yet. |
| Observability, tracing, immutable WORM audit, FinOps | `agent-observability` | **Tracing half.** The managed tracer exports OTLP to the `agent-observability` collector when the endpoint is configured; the audit trail is still this process's own store. |
| Agent registry, versioning, entitlements | `agent-registry` | **Not wired.** The A2A card is published but nothing registers it. |
| Runtime guardrail: prompt-injection defence, output filtering | `agent-guardrail-gateway` | **Not wired.** No `GuardrailPort` exists. Required before untrusted ticket text reaches any model. |
| Governed RAG and knowledge base | `enterprise-knowledge-base` | **Not used.** Nothing retrieves. A KB-article suggestion feature would consume `enterprise-knowledge-base`, not build a corpus here. |

### What about the rest of the service-desk lifecycle?

Out of scope here. Incident command and handover, change management, capacity and cost
forecasting, and the ticketing system of record itself are all somebody else's job; this repo
consumes a ticket and emits a routing decision. Check the
[organization's repository index](https://github.com/portable-genai) before building a
capability that may already have a home.

### How do I see it working?

`make demo` runs the presenter-paced walkthrough offline: it starts its own loopback server,
narrates each step on the terminal and drives the REAL services, including a step that plants a
national id and proves it is masked before the audit write, and a tamper step that deliberately
goes red. `make demo-selftest` is the same arc headless and asserted, `make demo-static` renders
the audit-first panels to dependency-free HTML for screenshots, and `make portability` runs the
executable portability claim. All of it is offline, stdlib-only, and uses obviously fictional
data. See [`../../DEMO.md`](../../DEMO.md).
