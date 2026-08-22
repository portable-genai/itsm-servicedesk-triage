"""Canonical synthetic cases, shared by the unit and contract suites.

Every party is obviously fictional and every address is an ``.example`` domain or an RFC 5737 /
RFC 3849 literal. One canonical escalating case and one canonical routine case are enough for
the contract suite: parity means the SAME request through every implementation, so the request
has to have one home rather than being retyped per test.
"""

from __future__ import annotations

from itsm_servicedesk_triage.domain.models import (
    AccessRequest,
    TriageInput,
)

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

#: A case that MUST escalate: the deterministic band is HIGH, so rule R8 routing applies.
ESCALATING_CASE = TriageInput(
    subject="Acme Holdings (FICTIONAL)",
    text="urgent data breach reported by the branch",
)

#: A case that must NOT escalate: a router that manufactured a review here would be lying.
ROUTINE_CASE = TriageInput(
    subject="Beta Trading (FICTIONAL)",
    text="routine note about a stationery order",
)

#: A planted identifier, so a redaction assertion has an independent literal to look for
#: rather than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: A second planted identifier, differently shaped, so a redaction assertion is not one pattern
#: agreeing with itself. It also sits in a field the NRIC does not, which is the point below.
PLANTED_EMAIL = "lim.wei@bank.example"

#: An escalating case that also carries personal data, for the redact-before-anything proofs.
PII_CASE = TriageInput(
    subject="Gamma LLP (FICTIONAL)",
    text=f"urgent breach, NRIC {PLANTED_NRIC} and mail ops@gamma.example on file",
)

#: A ticket shaped the way a service desk actually receives one: the requester's address is in
#: the SUBJECT line and the body quotes a national identifier. Both halves are caller-supplied and
#: both land in a citation the engine builds (the evidence citation's ``source_id`` is
#: ``ticket:<subject>`` and its snippet is the body), which is why one planted token in the body
#: was not enough to catch C3: the summary masked it and the citations beside it kept it.
PII_TICKET = TriageInput(
    subject=f"INC-4471 raised by {PLANTED_EMAIL}",
    text=(
        f"urgent data breach: staff record for NRIC {PLANTED_NRIC} was mailed to the "
        "wrong recipient"
    ),
)

#: The access-side equivalent. ``requested_role`` is caller-supplied free text, and the
#: fail-closed unknown-role path quotes it VERBATIM into a citation snippet, so a role string
#: carrying personal data is how the same defect reaches the WORM record on the access path.
PII_ACCESS_REQUEST = AccessRequest(
    request_ref="REQ-8802",
    subject_ref=f"{PLANTED_EMAIL} (NRIC {PLANTED_NRIC})",
    requested_role=f"payments_approver for {PLANTED_EMAIL} NRIC {PLANTED_NRIC}",
    current_entitlements=("payment.view",),
)
