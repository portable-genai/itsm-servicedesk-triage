# Model card: ITSM Service Desk Agent (H3)

**There is no model in this system's path today.** The README tagline calls the agent
"model-advised triage", and today no model advises it. This card exists to record that plainly,
and to fix the boundary a model would have to respect if one is ever added. It is a boundary
record, not a model description.

## The discrepancy, and the evidence

No generation, narration or LLM port is declared, bound or called in any profile. The whole port
surface is four modules in `ports/` (`audit.py`, `identity.py`, `observability.py`,
`review_router.py`), binding the five entries of `PORT_PROTOCOLS`: `audit`, `identity`,
`review_router`, `tracer`, `evaluation`. `config/settings.yaml` binds exactly those five for each
of `local`, `gcp` and `onprem`, and `adapters/local/` holds exactly the five matching modules
(`audit.py`, `evaluation.py`, `identity.py`, `review_router.py`, `tracer.py`). There is no sixth.

The intent is recorded in the code itself. `domain/triage_engine.py` says the engine computes the
category, priority, severity and queue from the taxonomy pack "with NO model in the loop", and
that if an LLM or a channel adapter does suggest a category, "the engine recomputes from the
ticket text itself and its computation WINS". `domain/access_engine.py` says the same for the
access side: the verdict is reached "with NO model in the loop. An LLM may narrate this
worksheet; it can never decide eligibility or an approver." `domain/models.py` documents
`TicketSignals` as the place a model's opinion would land: "An LLM (or a channel adapter's own
classifier) may fill these in from the ticket text", with every field a suggestion the engine
reads only to DETECT disagreement.

So the tagline describes an intended shape, and the shipped shape is the deterministic half of
it. That is the safer half.

## What produces the consequential outputs

All of it is deterministic, pure-stdlib, replayable code:

- the triage category, priority band, severity and QUEUE: `domain/triage_engine.py`, computed
  first-category-wins from `config/packs/triage/taxonomy.yaml`, with severity a pure function of
  the matched category's priority band;
- the segregation-of-duties verdict, the entitlement union, the findings and the approval chain:
  `domain/access_engine.py`, computed from `config/packs/access/policy.yaml`;
- the escalation itself: `_ESCALATING_SEVERITIES` in the triage engine, and, on the access side,
  an unconditional escalation because a grant is consequential by construction.

Same inputs, same outputs, every time, with no model available to change any of them.

## The boundary a model would have to respect

If a model is added, `domain/models.py` already names the only place its output may land: the
`TicketSignals` classification hints (`category`, `priority`, `affected_service`), which the
engine reads only to detect disagreement and surfaces as `model_agreed`. Specifically:

- a model may never produce the severity band, the queue, the SoD verdict, the eligibility
  decision or the approval chain;
- redaction happens BEFORE the model call, on the same rule that already governs the audit write
  (`domain/triage_service.py`), the outbound review payload (`adapters/_review_payload.py`) and
  the agent tool result (`agent/tools.py`, because a tool result becomes a model's context);
- every result still carries its `Citation` back to the pack clause that decided it;
- an escalated result still routes to the `human-review-console` in the same call that
  produced it (rule R8), and an access decision is consequential by construction, so it always
  routes and nothing is provisioned in-process.

## Controls that must exist BEFORE a model is introduced

1. **A generation port, properly registered.** A new port lives in the five places
   `CONTRIBUTING.md` names, or it runs with no enforcement at all: `ports/__init__.py`
   (`PORT_PROTOCOLS`), `config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`,
   and a `PortCase` in `tests/contract/canonical.py`. Then an adapter in all three families, with
   `onprem` refusing rather than pretending.
2. **A pinned model id and version, recorded in this file.** A promotion verdict is keyed to the
   exact model that produced the evidence, so an unpinned model invalidates the evidence.
3. **Budget and rate controls, and a kill switch** (P-10, P-11): a per-request token budget, a
   request rate limit, and a switch that forces deterministic-only operation with the model off.
4. **An eval that scores the live model.** `eval/run_eval.py` today scores the deterministic
   engines against hand-labelled `expected_*` oracles, and every metric is proven able to go red
   before its green is trusted. Add a managed-profile run through the `model-quality-gate` promotion gate that
   scores the model's own classification against the same golden sets.
5. **Prompt-injection screening on the ticket text**, through the `agent-guardrail-gateway`, failing
   closed to deterministic-only when the screen is unavailable. A ticket body is untrusted text
   written by whoever raised the ticket. This is the open R1 row in `COMPLIANCE.md`; PII
   redaction through `pii-kit` is a different control and does not substitute for it.

## Status

Model-free. Every consequential output is produced by a deterministic stdlib engine, so there is
no model risk to document, no prompt to version and no inference cost to govern. This card
records the boundary rather than a model, and it must be rewritten as a real model card, with
items 1 to 5 above complete, on the day a generation port is bound. Until then the "model-advised"
wording in the README is aspirational and should be read against this page. See
[`ADOPTING.md`](ADOPTING.md) and [`../COMPLIANCE.md`](../COMPLIANCE.md) (rows P-05, P-11, R1, R3).
