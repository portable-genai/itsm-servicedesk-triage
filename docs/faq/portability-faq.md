# Portability FAQ

For architecture, cloud and exit-planning reviewers who want to know how real the "no lock-in"
claim is, and how an off-cloud or sovereign exit would work. Cross-references:
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`../onprem-migration.md`](../onprem-migration.md).

## What is the no-lock-in claim, concretely?

The core (`domain/` and `ports/`) is standard library plus the catalog's own stdlib-only commons
packages. No cloud SDK, no web framework, no HTTP client. All infrastructure sits behind
`@runtime_checkable` Protocols in `ports/`, and which adapter binds is one setting. The rule is
enforced as an ALLOWLIST rather than an SDK blocklist (a blocklist rots the day a vendor renames
a distribution) by `tests/unit/test_core_purity.py`, which walks the AST of both core trees in
the offline gate.

## Is the domain really pure stdlib? What is the `yaml` exemption?

Almost, and the exception is recorded rather than hidden. `domain/packs.py` imports `yaml` to
parse the two policy packs, and that import is listed in `EXEMPT_IMPORTS` in
`tests/unit/test_core_purity.py` with its reason: service packs are parsed inside the core, and
extraction to the config boundary is queued. It is debt with a name on it, not an allowance: the
scan fails on any core import that is not stdlib, not a listed commons kit, and not in that
table, and the row is deleted when the parse moves out to the configuration boundary. The
portfolio-level gate reports it as a warning by design.

What it does and does not cost you: `pyyaml` is a pure-python, widely available dependency with
no cloud coupling, so it does not compromise the exit story. It does mean the honest sentence is
"stdlib plus the commons plus one recorded `yaml` import in the pack loader", not "pure stdlib".
Everything consequential (the engines in `domain/triage_engine.py` and `domain/access_engine.py`)
imports nothing outside the standard library and this package.

## What are the three profiles?

`ITSMDESK_PROFILE` selects the whole adapter stack, for all five bound ports at once:

- **`local`** (the dev, test and CI stack): a real, working, SDK-free offline family. Seeded dev
  personas, the hash-chained SQLite WORM audit log from the commons, the review kit's inspectable
  outbox (deliberately not a no-op), a no-op tracer, and an offline evaluator that scores but
  REFUSES to promote, because a promotion certified by a laptop with no quality service is
  certified by nothing.
- **`gcp`**: the managed family. Cloud Logging WORM, IAP identity, OTLP or Cloud Trace, the Hrz4
  promotion gate, the Hrz7 console over S2S. Every SDK import is LAZY, inside the method, so the
  other two profiles import this package with no cloud SDK installed.
- **`onprem`**: fail-fast placeholders that satisfy the same Protocols and RAISE rather than
  pretending, naming the migration target. A placeholder that returned successfully would be a
  false portability claim; on a serving path a bare `NotImplementedError` would be a 500 with no
  body, so the refusals carry a status and a reason.

An unset profile is its own state, not a silent `local`: the offline adapters bind, but the
seeded personas are refused, no S2S scheme is selected, and the exposure guard refuses every
non-loopback peer.

## Is the portability claim tested, or just asserted?

Tested, and executable. `make portability` runs eight named checks with a pass or fail each: port
map completeness, adapter construction and Protocol conformance, the offline family ANSWERING
(not merely not raising), the exit family REFUSING, in-place rewrite detection, anchored
truncation detection with its control case, the JSON Lines export and foreign reload, and the
no-cloud-SDK check. It prints what it does NOT prove and exits non-zero on any failure. Alongside
it, `tests/contract/test_port_parity.py` asserts set equality across all five homes of a port so
an unregistered port cannot run untested, `tests/contract/test_behavioral_parity.py` proves the
offline family answers, the exit family raises and the managed family refuses, and
`tests/contract/_sdk_free_probe.py` proves the lazy imports really are lazy by BLOCKING the
import in a fresh interpreter rather than relying on the SDK being absent from the machine.

## How would a sovereign or on-premises exit actually go?

The `onprem` profile is the scaffold: each fail-fast placeholder marks a seam where you supply
your own component (your IdP, your audit store, your review console, your trace backend, your
quality gate). The domain never changes, so the exit is an adapter exercise rather than a
rewrite. The audit trail exports to and restores from JSON Lines, so moving the evidence is a
file copy. The written path is [`../onprem-migration.md`](../onprem-migration.md) and the
operating notes are in [`../runbook.md`](../runbook.md).

## Is the policy portable too?

Yes, and this is the part most worth checking. The consequential policy is DATA, not code: the
triage taxonomy and the segregation-of-duties matrix are two YAML packs under `config/packs/`,
loaded strictly (an unknown field, a missing required field, a duplicate id or a conflict naming
an entitlement no role grants all REFUSE at load). Moving to another deployment means carrying
two files, not porting an engine. The one exception to name: two engine constants,
`_ESCALATING_SEVERITIES` in the triage engine and `_TIER_SEVERITY` in the access engine, are
module-level rather than pack fields.

## Is data residency portable across regions?

The region is selected once and shared by the runtime (`config/settings.yaml`) and Terraform, and
in Terraform `var.region` is validated against `var.allowed_regions` at plan time, so an
off-allowlist region fails `terraform plan` rather than reaching an apply. Moving to another
approved jurisdiction is a tfvars change plus the settings default, not a fork. The enforcement
layer (the `gcp.resourceLocations` org policy, the regional CMEK key ring, the VPC-SC perimeter)
is in `infra/terraform/` and gated on `var.enable_org_policies` and `var.enable_vpc_sc`.

## What is honestly NOT portable?

Tamper evidence is scoped to what the local sink can prove, and `portability_demo.py` says so
rather than overclaiming: production non-rewritability is the managed WORM sink's job (the locked
Cloud Logging bucket, and Hrz5 at the enterprise level). The managed identity adapter's
guarantees are IAP's, so an on-premises deployment substitutes its own IdP and its own assurance.
And nothing in the offline gate runs `terraform test`, so the residency assertions in
`infra/terraform/production_edge.tftest.hcl` are only as current as the last time somebody ran
them by hand.
