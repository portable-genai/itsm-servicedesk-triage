# Adoption FAQ

For an engineering lead forking this repo as their institution's service-desk base. The
step-by-step is [`../ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?"
questions.

### How do I rebrand it for my organisation?

`scripts/rename_fork.py` rewrites the python package (`itsm_servicedesk_triage`), the
console-script name, the `ITSMDESK` env-var prefix, the Terraform `name_prefix` stem (`h3-svc`)
and the distribution / git id (`itsm-servicedesk-triage`) in one simultaneous pass. Preview
with `--dry-run`, apply with `--yes`, add `--include-docs` to sweep Markdown prose. Then recreate
the venv (the distribution name changed), `make install`, and `make gate`.

One subtlety it handles for you: in this repo the console-script name IS the package name (see
`[project.scripts]` in `pyproject.toml`), so a naive sequential search and replace would rename
the command twice. Every rule is applied in one pass, and the CLI rules match only the two shapes
a command NAME appears in, so `from itsm_servicedesk_triage import ...` in
`scripts/portability_demo.py` stays a module path rather than becoming a command.

### If several institutions fork this, how does each take upstream fixes?

Track upstream via git tags. The repo declares a core-vs-adopter-owned boundary
([`../ADOPTING.md`](../ADOPTING.md) section 2): upstream owns the kernel types, `ports/`,
`tests/contract/`, the eval harness mechanics, CI and the `Container` wiring; you own the two
policy packs, the `config/settings.yaml` values, `adapters/onprem/*`, the PII jurisdiction list,
UI theming and the eval golden sets. Rebase your adopter-owned changes onto each release rather
than merging `main` continuously, so conflicts stay in the files you were told to expect.

### Where does my institution's policy actually live?

In two YAML packs under `config/packs/`, and that is the point:
`triage/taxonomy.yaml` (categories with their keywords, affected service, priority band, queue
and citation clause; the `p1..p4` to severity map; the defaults for an unmatched ticket) and
`access/policy.yaml` (roles with entitlements and risk tiers, the toxic-combination matrix, the
approval chain per tier). Both shipped files are illustrative and synthetic, and both are strictly
validated by `domain/packs.py`: an unknown field, a missing required field, a priority outside
`p1..p4`, a duplicate id, or a conflict naming an entitlement no role grants all REFUSE at load,
because a pack that silently dropped a field it did not recognise would be a policy nobody
reviewed. Exactly one file is expected in each directory.

Two things the packs do not carry, so plan for them: `_ESCALATING_SEVERITIES` in
`domain/triage_engine.py` (which bands escalate) and `_TIER_SEVERITY` in
`domain/access_engine.py` (risk tier to review severity) are module constants. The practices
audit records the "bank-owned numbers in config" item as an open B4 row.

### What does a fork inherit green but wrong?

The eval gate. `eval/run_eval.py` scores five metrics against hand-labelled oracles in
`eval/datasets/golden_cases.jsonl` and `eval/datasets/access_cases.jsonl`
(`decision_accuracy` and `routing_accuracy` at 0.80, `pii_safety` at 0.99, `sod_precision` and
`sod_recall` at 1.00). Those golden cases describe THIS taxonomy and THIS matrix. Swap the packs
without rebuilding the datasets and the gate stays green while measuring the wrong thing. The
harness structure and the can-go-red proof are generic; the golden cases are yours.

The same applies to the fixtures (`tests/fixtures/sample_cases.py`), the demo cases in
`scripts/demo.py`, and the `JURISDICTIONS` list in `domain/pii.py`.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and the contract test enforces it, because four of the five homes can
be satisfied while the fifth is missing and the result is a port with zero enforcement and a
green build. The five homes are `ports/__init__.py` (`PORT_PROTOCOLS`),
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`; then three adapters, where `local` WORKS offline, `gcp` imports
its SDK lazily and `onprem` RAISES with a status and a reason.
`tests/contract/test_port_parity.py::test_every_home_of_the_port_set_agrees_exactly` asserts set
equality across all five. The full row-by-row list, including which test enforces each row, is in
[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I add a model?

Deliberately, and not first. See [`../model-card.md`](../model-card.md): the system is model-free
today, the boundary a model may occupy is already written down (the advisory `TicketSignals`
hints, never the band or the verdict), and five controls have to exist before a generation port
is bound, including the `agent-guardrail-gateway` screen and an eval that scores the live model.

### How do I add a new surface, or a new deterministic engine?

A surface routes escalations (rule R8) and minimises what it hands a model; an agent tool also
needs its skill in `agent/agent_card.py`, because the card and the tool table are compared for
set equality. A new engine in `domain/` keeps the consequential decision pure stdlib and
replayable, and escalates through `ReviewRouterPort` rather than terminating in a boolean. A new
demo step needs both its `Step` in `scripts/demo.py` and its entry in `walkthrough.CHECKS`, with
the numbers a check reads placed in the step's `facts` dict rather than only in rendered prose.

### Will the demo rot after I diverge?

It is guarded from two directions. `tests/unit/test_demo_surface.py` runs inside `make gate`: it
holds `demo.STEPS` and `walkthrough.CHECKS` equal so a step cannot narrate a claim nobody checks,
drives the whole arc against the real adapters, asserts the tamper step actually goes red, and
fails if a script stops being listed in `scripts/README.md`. The hosted check runs the
same walkthrough headless on every pull request and every push to main, plus
`make portability`. Keep the `facts` dicts and the step keys when you diverge; they are the
contract every stage reads.

### Does the gate run for my fork out of the box?

Yes. `make gate` is offline and credential-free: no cloud SDK, no project, no network. The
workflows reference no organisation secrets. You add credentials only when you wire the `gcp`
profile. Note that `make docs-check` enforces the house style on shipped prose (relative links
must resolve, code fences must close, and no em-dash or en-dash may appear), and
`tests/unit/test_docs_links.py` runs the same functions inside the gate, so a broken link in your
own documentation fails the build.
