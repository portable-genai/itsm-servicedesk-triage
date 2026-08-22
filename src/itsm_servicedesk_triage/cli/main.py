"""Minimal stdlib CLI: triage a case, or assess an access request (argparse, no extra deps)."""

from __future__ import annotations

import argparse
import sys

from hex_service_kit.logging import configure_logging

from ..config import build_container
from ..domain.access_service import AccessService
from ..domain.models import AccessRequest, TriageInput
from ..domain.triage_service import TriageService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="itsm_servicedesk_triage")
    sub = parser.add_subparsers(dest="command", required=True)

    triage_cmd = sub.add_parser("triage", help="Triage a single case.")
    triage_cmd.add_argument("subject")
    triage_cmd.add_argument("text")
    triage_cmd.add_argument("--actor", default="cli-user@bank.example")
    triage_cmd.add_argument("--tenant", default="", help="Tenant partition asserted to Hrz7.")

    access_cmd = sub.add_parser("access", help="Assess a single access request.")
    access_cmd.add_argument("request_ref")
    access_cmd.add_argument("subject_ref")
    access_cmd.add_argument("requested_role")
    access_cmd.add_argument(
        "--current",
        action="append",
        default=[],
        metavar="ENTITLEMENT",
        help="An entitlement the subject already holds (repeatable).",
    )
    access_cmd.add_argument("--actor", default="cli-user@bank.example")
    access_cmd.add_argument("--tenant", default="", help="Tenant partition asserted to Hrz7.")

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="itsm-servicedesk-triage")

    if args.command == "triage":
        service = TriageService(container.audit, tracer=container.tracer)
        result = service.triage(TriageInput(subject=args.subject, text=args.text), actor=args.actor)
        print(f"{result.subject}: {result.severity.value} ({result.decision.value})")
        print(f"  requires_human_review: {result.requires_human_review}")
        if result.requires_human_review:
            # Rule R8 on the CLI path too: the same escalation, the same router. A surface that
            # only printed the flag would be a second place for an escalation to stop.
            ref = container.review_router.route(result, maker=args.actor, tenant=args.tenant)
            print(f"  routed to human review: {ref}")
        return 0

    if args.command == "access":
        access_service = AccessService(container.audit, tracer=container.tracer)
        decision = access_service.assess(
            AccessRequest(
                request_ref=args.request_ref,
                subject_ref=args.subject_ref,
                requested_role=args.requested_role,
                current_entitlements=tuple(args.current),
            ),
            actor=args.actor,
        )
        verdict = "eligible" if decision.eligible else "BLOCKED"
        print(
            f"{decision.subject}: {decision.requested_role} -> {verdict} "
            f"({decision.severity.value})"
        )
        for finding in decision.findings:
            print(f"  finding [{finding.code}]: {finding.detail}")
        print(f"  approval chain: {' -> '.join(decision.approval_chain)}")
        # Rule R8: every access grant is consequential, so it always routes. There is no branch
        # that provisions without a human, which is the whole point of the access engine.
        ref = container.review_router.route(
            decision, maker=args.actor, tenant=args.tenant, action="access"
        )
        print(f"  routed to human review: {ref}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
