# Pinpoint 311 — What We're Building and Why

Plain-language overview of the project and where it's headed. For engineering
detail see `ORCHESTRATOR_PLAN.md`; for the hosted-model scope see
`HOSTED_MODEL_SCOPE.md`.

## The problem

Most towns either have no way for residents to report problems (potholes,
broken streetlights, missed trash, code issues) or they pay a vendor a lot of
money for a closed "311" system. Small and mid-size municipalities get priced
out, end up with clunky tools, and their data lives inside someone else's
platform. Staff re-key the same request into three systems.

## What Pinpoint 311 is

An **open-source municipal 311 platform**: residents report issues from a phone
or the web, staff triage and resolve them, and everything (photos, comments,
status) syncs with whatever other government systems the town already runs. It
is built to be:

- **Free and open** — no per-seat licensing; a town owns its data.
- **Set up by a non-technical clerk** — guided, point-and-click, plain
  language, no config files or command line.
- **Genuinely secure** — resident PII encrypted at rest, tamper-evident audit
  trail, and honest about what each feature actually does.
- **Not locked to one cloud** — the AI, translation, sign-in, secrets, and key
  management are all pluggable (Google *or* Microsoft/Azure Government *or*
  AWS), so a state or town uses the stack it's already approved for.

## Two ways to run it

1. **Self-hosted** — a single town runs its own instance. Everything above
   applies as-is. This is the default and always stays fully functional.

2. **State-hosted (centralized)** — a state agency (e.g. the NJ Innovation
   Authority / DCA) hosts many towns at once. The state runs the servers and
   domains; each town still configures its own connections and brings its own
   API keys. This is what the **orchestrator layer** enables.

## Who is responsible for what (the three-party model)

The whole design follows one rule — clear ownership boundaries:

- **Pinpoint 311 (the org)** — writes and maintains the code. No runtime cost,
  no access to any town's data.
- **The State** — runs the hosting: servers, domains, backups, the shared key
  vault, and the orchestrator that provisions and updates each town. Sees only
  *metadata* (health, versions, usage totals) — never resident data.
- **The Town (jurisdiction)** — configures the app for itself: branding, which
  external systems to connect, and its own API keys, which it pays for
  directly. Full control of its own data.

## How isolation works (the safety guarantee)

Each town is a **completely separate instance** — its own database, cache,
storage, encryption key, and secrets. There are no shared tables and no
tenant-id columns to get wrong, so one town's data physically cannot leak into
another's. When a town leaves, destroying its encryption key makes its data
unrecoverable instantly (crypto-shredding) — a clean, provable deletion story.

## What the orchestrator adds

A **separate control plane** the state operates. It:

- provisions a new town in one flow (database, keys, domain, TLS, deploy),
- ships new versions to the whole fleet safely (canary rollouts, auto-rollback),
- shows fleet-wide health and cost — as metadata only,
- injects only the *state-owned* secrets; a town's own keys never pass through
  it,
- gives the state audited, time-boxed "break-glass" support access.

Crucially, the orchestrator sits *above* the app and never handles resident
data. The app keeps running stand-alone; a set of flag-gated hooks
(`MANAGED_MODE`) let the orchestrator drive it when hosted.

## Principles we hold to

- **Additive, never destructive** — hosted-mode features are flags; turning
  them off returns the exact single-town behavior.
- **No advertised-but-fake features** — if a capability is shown in the UI, it
  is wired end-to-end. Connectors that ship configurable defaults say so
  instead of claiming "full sync."
- **PII-safe by default** — resident data is encrypted, never logged, never
  sent to the control plane, and requires elevated access to export in bulk.
- **Approachable** — the person setting this up is a town clerk, not a DevOps
  engineer.

## Where things stand

- **Built today:** resident intake, staff dashboard + manual (call-taker)
  intake, AI triage, translation, govtech integrations (Accela, Tyler,
  CivicPlus, Cityworks, Open311, and more), pluggable providers
  (AI / translation / identity / KMS / secrets),
  envelope-encrypted PII, HMAC-keyed tamper-evident audit log, point-and-click
  setup for non-technical staff.
- **Planned:** the orchestrator layer and the `MANAGED_MODE` hosted-mode hooks
  — see `ORCHESTRATOR_PLAN.md` for the file-level build plan.
</content>
