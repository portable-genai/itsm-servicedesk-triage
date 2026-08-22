# FAQ index

Answers to the questions different teams ask when evaluating, adopting, or reviewing this
repository (H3, the ITSM Service Desk Agent) as a common base for a service-desk agent. Each
file is written for a specific audience; skim the one that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | server-side identity, the exposure guard, the PII posture, secrets, supply chain, the anchored audit chain, what is out of scope |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | the no-lock-in claim and its one recorded exemption, the three profiles, the executable portability check, the on-premises exit |
| [features-faq.md](features-faq.md) | Product / service management / delivery | what the two verticals produce, what is deterministic (all of it), what the agent will not do, and the boundary with sibling systems |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | rebranding, taking upstream fixes, the policy packs, extension points, what a fork inherits green but wrong |
| [compliance-faq.md](compliance-faq.md) | Compliance / operational risk / model risk | maker-checker, residency, the audit trail, the eval gate, and which rows are still open |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the
catalog. Where a concern belongs to another repo (the guardrail gateway Hrz1, the knowledge base
Hrz2, the agent registry Hrz3, the quality gate Hrz4, observability and WORM audit Hrz5, the
human-review console Hrz7), the FAQ points at it and explains where this repo's responsibility
stops rather than duplicating it. See [features-faq.md](features-faq.md) for the full "what this
repo owns vs what it integrates" map, and [`../ADOPTING.md`](../ADOPTING.md) for the fork path.
