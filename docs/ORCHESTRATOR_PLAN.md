# Orchestrator Layer — Build Plan & Downstream Changes

> Start with `VISION.md` for the plain-language "what we're trying to do."
> `HOSTED_MODEL_SCOPE.md` (on the `hosted-model-scope` branch) scopes *what*
> the state-hosted model is. **This doc is the execution plan**: exactly how to
> build the orchestrator, and every concrete change required in this app repo —
> grounded in the current code so a developer can pick it up file-by-file.

> **Implementation status:** Part B (the orchestrator) is built in the
> `centralizedhosting` repo. Part A hooks A1–A5 + A8, plus A7 suspend/resume,
> are implemented in this repo (`app/core/managed.py`,
> `app/api/provisioning.py`, `app/api/telemetry.py`, health stamping, managed
> gates in `app/api/system.py`). Remaining: A6 verification passes, A7
> whole-instance export archive, cloud drivers on the orchestrator side.

## Mental model in one paragraph

The app you have today **is** the per-town unit — one instance = one
jurisdiction, its own DB, Redis, storage, KMS key, and secrets (silo
multi-tenancy, no shared tables). The **orchestrator** is a *separate control
plane* that never touches resident data: it provisions towns, injects only
platform-managed secrets, rolls out new versions, and aggregates health/cost
metadata. The app stays runnable stand-alone; a set of **additive, flag-gated
hooks** let the orchestrator drive it when `MANAGED_MODE=true`. Nothing about
the single-tenant behavior changes when the flag is off.

Two workstreams:
- **A — Downstream app changes** (this repo). Additive, testable today, ship
  incrementally on `main`. This is the bulk of the risk and the part you asked
  about.
- **B — The orchestrator itself** (new repo). Greenfield control plane that
  depends on the app *only by container image tag + its provisioning/telemetry
  API* — never by source.

---

# Part A — Downstream changes in this app repo

Ordered by dependency. Each is independently shippable and guarded so it is a
no-op in standalone mode.

## A1. `MANAGED_MODE` flag + the secret split (foundation)

**Why first:** every other hook keys off it.

- Add `managed_mode: bool = False` to `app/core/config.py` `Settings`.
- Define the **platform-managed key set** (state owns) vs **tenant-managed**
  (town owns). Platform-managed: `SECRET_KEY`, `DATABASE_URL`, KMS refs
  (`GOOGLE_CLOUD_PROJECT`/`KMS_*`/`AZURE_KEYVAULT_*`), `BACKUP_*`,
  `PROVISIONING_TOKEN`, domain/DNS. Tenant-managed: everything in the provider
  catalogs (AI/translation/identity keys), SMTP/SMS, branding.
- **Enforcement point:** `app/api/system.py` `_persist_secret` and the
  `POST /system/secrets` handler. When `managed_mode` is on, reject writes to
  any platform-managed key with `403` ("Managed by your state"). This is a
  ~10-line guard at one choke point — every provider save already funnels
  through `_persist_secret`.
- **UI:** `SetupIntegrationsPage.tsx` — hide the Google Cloud / Backups /
  domain cards when a new `/system/config` field `managed_mode` is true; show
  a locked "Managed by your state" placeholder. Provider/integration/branding
  cards stay fully editable.

**Downstream ripple:** the setup progress tracker counts must exclude
platform-managed steps in managed mode, or they'll always read "incomplete."

## A2. Disable in-app self-update in managed mode (**top security fix**)

**This is the single biggest infra risk and the audit's headline item.**
`app/api/system.py` lines ~1451–1560 shell out via `subprocess` to
`git pull` + `docker compose` through a mounted Docker socket. In hosted mode
a compromised admin token → host takeover across the shared cluster.

- Gate the `/system/update`, version-switch, and runbook endpoints behind
  `if settings.managed_mode: raise HTTPException(403, "Upgrades are managed by your state")`.
- Remove the Docker socket mount from the hosted deploy manifest (compose/helm).
- Upgrades in hosted mode come **only** from the orchestrator (publish image →
  panel rolls out). Standalone self-host keeps the feature.

## A3. Version + migration stamping on health (enables safe rollouts)

The orchestrator must detect drift and gate canary rollouts on DB
compatibility. Today `app/api/health.py` `GET /` returns no build/version.

- Add `APP_VERSION` (from image build arg / env) and the current + minimum
  Alembic revision to the health payload: `{version, git_sha, db_revision,
  min_db_revision}`.
- Confirm Alembic migrations run idempotently on boot (they mostly do — see
  `app/db/init_db.py`). Enforce **expand/contract** (backward-compatible)
  migrations so a canary running new code against not-yet-migrated peers, and
  old code against a migrated DB, both work. Document this as a hard rule.

## A4. Non-interactive provisioning API

Replaces the interactive first-run bootstrap when the panel creates a town.

- New router `app/api/provisioning.py`, auth = `PROVISIONING_TOKEN` header,
  **constant-time compare** (`hmac.compare_digest`), endpoints active only when
  the token is set. Endpoints: set township name/branding, set external
  domain, create/assign initial admin, return a **one-time onboarding link**
  (short-lived signed token).
- Reuses existing setup logic in `app/api/setup.py` — factor the town-creation
  bits into a service both the interactive and provisioning paths call.

## A5. PII-safe telemetry endpoint

- `GET /telemetry`, panel-token auth, **metadata only**: version, uptime,
  request counts by status, integration health counts, API-usage/cost totals
  (the `api_usage` table already aggregates this). **Never** resident data.
- Add a test asserting the response schema contains no PII field — a
  regression guard, since this is the one endpoint the panel scrapes fleet-wide.

## A6. Data-isolation & logging hardening (mostly verification)

- Confirm no cross-tenant global state. **One real item found in the audit:**
  the audit-log `_audit_seq` counter and the secret-manager module caches are
  per-process — fine for silo (one process set per town), but must be
  re-verified if you ever co-locate tenants in one process (don't).
- Per-town object-storage prefix/bucket for uploads.
- **Hosted-mode logging must be PII-scrubbed at the shipper.** The recent audit
  already redacted vendor error bodies and token responses; in managed mode
  make PII-safe logging a hard requirement (central log aggregation).

## A7. Lifecycle hooks

- **Export** — full town data export for offboarding / open-records (extends
  the existing `data_export.py`; add a whole-instance archive variant).
- **Suspend/resume** — honor a panel-set state: read-only or offline banner,
  without deleting.
- **Decommission / crypto-shred** — on offboard the panel destroys the town's
  KMS key. With envelope encryption (`pii_crypto.py`) this is now clean: **all
  PII becomes unrecoverable the instant the wrapping key dies**, because every
  DEK is wrapped by that key. Set `REQUIRE_KMS=true` per tenant so there's no
  local-key fallback that would survive the shred. *(This is a concrete payoff
  of the envelope-encryption refactor — document it as the deletion story.)*

## A8. Break-glass access path

- Panel-issued, time-boxed, **audited** state-ops impersonation, distinct from
  town staff login, written into the town's own (now HMAC-keyed) audit trail.
- Leans on the identity layer (`identity.py`) — add a provisioning-signed
  short-lived token accepted only when `managed_mode` and logged as
  `actor_type="state_ops"`.

---

# Part B — The orchestrator (new repo)

Greenfield. Depends on the app by **image tag + provisioning/telemetry API**,
never source. Suggested stack: same FastAPI+React the team knows, or a
lighter admin framework — the logic matters more than the framework.

## B1. Tenant registry
Town, subdomain/custom domain, region, plan, status, running version,
contacts. **Metadata only — no resident data ever.** This table doubles as the
StateRAMP/FedRAMP authorization-boundary inventory.

## B2. Provisioner
Per town, in order: create DB → generate `SECRET_KEY` → create/assign KMS key
→ allocate storage bucket → set DNS + request TLS → deploy app image @ version
→ call the app's **A4 provisioning API** to set township + admin → email the
one-time onboarding link. Idempotent and re-runnable.

## B3. Release management
Org publishes a versioned image → panel schedules a **canary rollout** across
the fleet, runs migrations, watches the **A3 health/version** endpoint,
auto-rolls-back on failure, and enforces `min_db_revision` compatibility before
promoting. This is why A3's stamping exists.

## B4. Fleet dashboard
Health/version/cost aggregation from **A5 telemetry**, drift detection, per-town
status, integration health across all towns.

## B5. Secrets brokering
Only **platform-managed** secrets (DB creds, `SECRET_KEY`, KMS refs, backup
creds). Tenant-managed keys **never touch the panel** — the town enters them in
its own instance (this is what A1's split enforces from the app side).

## B6. Break-glass + compliance
Audited, time-boxed access (pairs with A8). Central audit of every
provisioning/rollout/support action.

---

# Deployment shape

- **Target:** Kubernetes, one Helm release (or namespace) per town on a shared
  cluster, GitOps-driven (Argo/Flux). Panel commits a tenant manifest → GitOps
  reconciles → canary upgrades are trivial.
- **MVP shortcut:** panel renders per-town Compose stacks on managed hosts;
  graduate to k8s later.
- TLS: wildcard `*.311.state.gov` via cert-manager, plus on-demand ACME for
  custom domains.

---

# Sequencing (what to build in what order)

1. **A1 + A2 + A3** — flag, kill self-update in managed mode, version stamping.
   All additive, testable in the existing app today. *Ship these first; A2
   alone closes the biggest infra risk even before any orchestrator exists.*
2. **A4 + A5** — provisioning + telemetry APIs (the panel's contract surface).
3. **B1 + B2** — registry + provisioner; provision one real town end-to-end.
4. **B3** — release management (canary + migration gating).
5. **A7 + A8 + B4 + B6** — lifecycle, break-glass, fleet dashboard, billing view.
6. **Provider abstraction polish** — already largely done (AI/translation/
   identity/KMS/secrets are pluggable); only revisit if a Microsoft-native
   state needs the Maps swap (Google → Esri), the one hard remaining seam.

---

# Open decisions to settle before building (from scope doc §7)

1. **KMS ownership** — recommend **state-provided shared HSM/Key Vault with a
   per-town key** (crypto-shred on offboard, no per-town HSM cost floor); set
   `REQUIRE_KMS=true` per tenant. The envelope scheme (A7) makes this the clean
   choice.
2. **Provider per state** — is the Maps abstraction (Google→Esri) in v1 or
   deferred? Everything else is already pluggable.
3. **Identity boundary** — commercial IdP (Auth0) vs gov-authorized
   (Okta-for-Gov / Entra in Azure Gov) for staff who can reach PII.
4. **Shared-key chargeback** — "town brings own key" (recommended, no
   invoicing) vs shared-key metering + billing.
5. **Data residency / region** per town.

---

# What does NOT change downstream (reassurance)

- Single-tenant / self-host behavior is untouched when `MANAGED_MODE` is off —
  every hook is flag-gated.
- The data model stays silo (no shared/tenant-id tables); isolation is by
  instance, so there's no risk of a cross-tenant query bug.
- Providers, integrations, audit log, PII encryption, manual intake — all the
  work already on `product-upgrades` — carry over unchanged; the orchestrator
  sits *above* them.
