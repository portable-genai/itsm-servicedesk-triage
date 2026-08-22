"""ReviewRouterPort: the boundary that routes an escalated result to Hrz7 (rule R8).

Rule R8 is the reason this port exists. A producer that sets ``requires_human_review`` MUST hand
the item to the Hrz7 Human-Review and Maker-Checker Console; terminating the escalation in a
per-repo boolean is the failure this port removes, because a flag nobody reads is
auto-execution with extra steps. Setting the flag and calling :meth:`route` is one act, not two
optional ones: ``api.app`` and the CLI both call it on every escalated result.

The domain stays pure. This port names the hand-off; the adapters (not this module) depend on
the shared ``review-kit`` client and perform the S2S submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.kernel import ReviewableResult


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(
        self, result: ReviewableResult, *, maker: str, tenant: str = "", action: str = "review"
    ) -> str:
        """Route an escalated result to Hrz7 and return the routing reference.

        ``result`` is any :class:`~..domain.kernel.ReviewableResult`: both this vertical's
        producers (ticket triage and access provisioning) satisfy it, so one router serves every
        surface. ``action`` labels which producer escalated (``triage`` / ``access``), so the
        console and the idempotency key can tell two verticals apart; it defaults to a neutral
        value so a caller that does not distinguish still routes.

        ``maker`` is the VERIFIED principal that originated the underlying decision, never a
        client-asserted actor. The return value is the console's review id where the console
        answered, or a local queue reference where the submission was buffered; it is never
        empty, so a caller can record what happened to the escalation.
        """
        ...
