# Pinpoint 311 — Centralized Hosting Build Plan

Execution plan for the state-hosted, instance-per-jurisdiction model behind the
NJIA/DCA proposal. Companion to `HOSTED_MODEL_SCOPE.md` (which holds the
proposal→status map and open decisions). This doc is the **what-gets-built,
where, by whom, and in what order**.

---

## 1. Architecture in one paragraph

**Silo multi-tenancy.** Each jurisdiction runs as a fully isolated instance of
the existing app — its own database, `SECRET_KEY`, encryption key, object
storage, and network namespace. Cross-town data bleed is impossible because
there is no shared data store. A separate **orchestration panel** (new repo)
provisions and operates the fleet but handles **metadata only** — never town
request data or PII. Every external capability sits behind a **provider
interface** so a jurisdiction runs on the cloud its state already uses.

**Three parties:** Pinpoint 311 (code) · Host/State (infra + panel) · Town
(configuration + its own API keys, billed directly).

---

## 2. Two repositories

### Repo A — `pinpoint-311` (this repo, the data-plane unit)
The town-facing application. Ships as versioned container images. Changes here
are **additive** — the app stays runnable standalone (a town or university can
self-host it with zero panel).

### Repo B — `pinpoint-control-plane` (new, the orchestration panel)
State-operated. Provisions/updates/monitors instances. Depends on Repo A by
**image tag**, never by source. Highest-sensitivity code (can reach every
tenant) → its own access controls, audit, and review gate.

---

## 3. Repo A — features to CLOSE / build in the app

### 3.1 Hosted-mode hooks (new, additive)
| Item | What it does |
| :--- | :--- |
| `MANAGED_MODE` flag | Hides infra/server/backup/domain settings from the town UI and rejects writes to platform-managed secrets (§6). Town sees only config it owns. |
| Provisioning API | Token-authenticated (`PROVISIONING_TOKEN`, constant-time) endpoint the panel calls to set township name, domain, initial admin, and return a one-time admin onboarding link. Powers the "afternoon browser setup." |
| PII-safe telemetry | `GET /telemetry` (token-auth) → version, uptime, request counts by status, integration health, API-usage/cost totals. **No resident data.** |
| Disable in-app self-update | In managed mode, `/api/system/update` (Docker-socket path) is disabled — the panel deploys updates. Removes the top infra risk from the audit. |
| Version + migration stamping | Health endpoint reports build version + min DB revision so the panel gates rollouts and detects drift. |
| Alembic-on-boot | Idempotent, backward-compatible (expand/contract) migrations for zero-downtime canary upgrades. |
| Lifecycle hooks | Full data **export** endpoint (offboarding/OPRA); **suspend/resume** honoring a panel flag; **decommission** hook that lets the panel destroy the town key (crypto-shred). |

### 3.2 Core product upgrades — ship to BOTH self-hosted and centralized
These are genuine product improvements, not hosting features, so they land in
the base app for every deployment (not gated to managed mode).
| Item | Work |
| :--- | :--- |
| Immutable request audit log | Extend the SHA-256 hash-chain (already on the auth `AuditLog`) to `RequestAuditLog`, so "immutable, tamper-evident" is literally true for OPRA. Add a verify endpoint. Benefits every town, hosted or self-hosted. |
| Safety-flag surfacing | AI already emits `safety_flags`; add prominent staff-dashboard surfacing + an at-risk queue so hazards don't sit unnoticed. Core improvement for all deployments. |

*Deferred:* NJDOT/state-county road detection — out of scope for now.

### 3.3 Security hardening carryover (from the audit)
- Already remediated: `SECRET_KEY` enforcement, PII/KMS handling + `REQUIRE_KMS`, SSRF guard, auth-bootstrap hardening, opt-in PII export, comment authz, rate limits, `_flag` PII-share gate.
- Close for production: remove Docker-socket self-update in hosted mode (done via §3.1), **central-log PII scrubbing** (hard requirement once logs ship to a state sink), CSP tightening review, dependency pinning + failing CI on high-severity.

### 3.4 Provider abstraction layer (new seams — phased, see §8)
Define one interface per capability and select via config. Scope is the
capabilities the stack actually varies on:
`IdentityProvider (OIDC)`, `AIProvider (provider, model)`, `TranslationProvider`,
`SecretStore`, `KeyManager`. Existing services (`auth0_service`,
`vertex_ai_service`, `translation`, `secret_manager`, `encryption`) become the
first implementations behind these, with Azure/AWS adapters added.

Identity generalizes cleanly because the app already authenticates via **OIDC**
(Auth0 today): a single generic OIDC adapter — config'd with issuer, client
id/secret, JWKS, audience, scopes — covers **Auth0, Microsoft Entra ID, Okta**,
and any OIDC-compliant IdP. Auth0 stays the default so existing deployments are
unchanged.

**Unchanged (no abstraction):** **Maps/geocoding stays Google Maps** as today;
SMS (Twilio/HTTP) and Email (SMTP) already support any provider. Object storage
is a host deployment choice (S3-compatible or Azure Blob), not a product change.

### 3.5 All providers pre-built and point-and-click configurable (hard requirement)
Every adapter listed in §7 ships **pre-built in the image** — switching
providers is **never** a code change, rebuild, or redeploy, only a
configuration choice. The configuration experience must be **as easy as or
easier than** today's Auth0 + Google setup.

Concretely, each provider reuses the existing clerk-friendly Setup &
Integrations pattern already in the app (the guided cards + wizard we built for
govtech connections):
- **Provider picker per capability** — e.g. AI shows *Vertex AI · AWS Bedrock ·
  Azure Government AI*; Identity shows *Auth0 · Entra ID · Okta* — as selectable
  cards, with a one-line plain description of each.
- **Plain-language fields with examples and inline hints** for every credential
  and setting (same `field_help` pattern), so a non-technical clerk can paste
  what the vendor sent without knowing what it is.
- **"Test connection" live check** with friendly, human-readable errors
  (the same translated-error UX), and **auto-enable on success**.
- **Write-only secret handling** — configured secrets show "saved — leave blank
  to keep," never re-displayed.
- **Two-level pickers where relevant** — AI shows a **model** dropdown under the
  chosen boundary (e.g. Gemini Flash-Lite / Claude / GPT-4o-mini).
- **Sensible defaults pre-filled** per stack, so the common path is mostly
  "confirm and test."
- **Managed-mode aware** — host-owned providers (secrets/KMS, and identity when
  the state sets it) render as read-only "Managed by your state"; town-owned
  providers (AI, translation, and identity when town-set) stay fully editable
  with the guided wizard.

Definition of done for each adapter includes its **config card + field hints +
Test-connection check**, not just the backend implementation. An adapter is not
"done" until a non-technical admin can select and configure it end-to-end in the
browser.

### 3.6 Design consistency — premium glassmorphism + accessible (hard requirement)
Every new surface — provider config cards, the AI model picker, telemetry
views, and the orchestration panel (Repo B) — must match the app's existing
**premium glassmorphism design language** *and* stay **WCAG 2.1 AA accessible**.
This is non-negotiable and part of every UI DoD:
- Reuse the existing `components/ui` primitives (`Card`, `Button`, `Input`,
  `Select`, `Modal`, `Badge`) and Tailwind design tokens — no bespoke styling
  that drifts from the current look (frosted panels, subtle gradients, soft
  shadows, rounded-2xl, consistent spacing).
- Motion via framer-motion, **always honoring `prefers-reduced-motion`**.
- Accessibility: full keyboard operability, visible focus states, AA contrast
  (including on glass/translucent backgrounds), ARIA roles/labels on toggles
  and pickers, screen-reader-friendly status/errors. The existing accessibility
  CI gate applies to all new surfaces.
- The orchestration panel shares the same design system so the whole platform
  reads as one product, not a separate admin tool.

### 3.7 Prebuilt integrations — design, performance & "as prebuilt as possible"
Enhance the existing govtech connectors *and* apply the same bar to the new
provider adapters:
- **As fully prebuilt as possible.** Each connector/adapter bakes in every
  sensible default so the admin enters the *minimum* — ideally just a URL + key
  (or just a key): auth style, endpoint paths, field mappings, status
  vocabulary, model catalogs (e.g. Azure OpenAI / Bedrock / Vertex model
  lists), region lists, and per-vendor setup guidance + request-email templates
  are all shipped. Goal: the common path is "pick provider → paste key → Test →
  done."
- **Design polish.** Bring every integration/provider card to the same premium,
  consistent glassmorphism standard (status chips, health indicators, sync
  activity, empty/loading/error states) — no rough edges relative to the rest
  of the admin console.
- **Performance.** Code-split the heavy admin bundle (current build warns on a
  ~1.4 MB chunk); lazy-load the integrations/provider views; cache the
  catalog; virtualize/paginate sync-activity logs; debounce and use optimistic
  UI on saves/tests. Backend: reuse pooled HTTP clients, run pushes
  concurrently, and cache catalog/health lookups so the panel and cards stay
  snappy at fleet scale.
- **DoD:** connecting any integration or provider is fast, visually consistent,
  and requires the fewest possible fields, with clear loading/success/error
  states throughout.

---

## 4. Repo B — orchestration panel (what we build new)

| Module | Responsibility | Key data / APIs |
| :--- | :--- | :--- |
| **Tenant registry** | Source of truth for tenants (metadata only) | tenant, subdomain/custom domain, region, plan, status, running version, contacts, provider selections |
| **Provisioner** | Stand up a town in minutes | create DB → generate `SECRET_KEY` → create/assign encryption key → allocate object-storage prefix → set DNS → request TLS → deploy image@version → call app provisioning API → email onboarding link |
| **Release manager** | Org publishes image → fleet upgrade | canary cohorts, migration-compatibility gate, health watch, auto-rollback |
| **Fleet dashboard** | Operate the fleet | aggregated health/version/cost, drift, integration-health across towns |
| **Billing visibility** | "town pays for usage" transparency | pull each town's `/telemetry` usage/cost; per-town + statewide rollup (read-only; direct billing stays town↔cloud) |
| **Break-glass support** | Org/state assist a town | panel-issued, time-boxed, audited access; logged in the town's own audit trail |
| **Secrets brokering** | Only platform-managed secrets | DB creds, `SECRET_KEY`, key refs, backup creds. Tenant secrets never touch the panel. |
| **Lifecycle** | Provision / suspend / offboard | export + crypto-shred; suspend without delete |
| **Ops audit + inventory** | Compliance record | immutable log of all provisioning/rollout/support actions; tenant inventory = authorization-boundary record |

Deployment target: **Kubernetes, one namespace/Helm-release per town**, GitOps
(Argo/Flux) reconciling panel-authored tenant manifests. **MVP shortcut:** panel
renders per-town Compose stacks on managed hosts; graduate to k8s later.

---

## 5. Data storage — what lives where

| Store | Scope | Contents | Isolation |
| :--- | :--- | :--- | :--- |
| **Town Postgres (+PostGIS)** | Per town | All town data: requests, PII (encrypted), comments, audit, map layers, integration configs/creds (encrypted), settings | Separate database per town; separate credentials |
| **Town Redis** | Per town | Cache, Celery broker | Per-instance (namespaced/separate) |
| **Town object storage** | Per town | Uploaded photos / media | Separate bucket or key-prefix per town |
| **Town encryption key** | Per town | KMS/HSM key encrypting that town's PII; `SECRET_KEY` derives Fernet fallback | Unique per town → crypto-shred on offboard |
| **Town backups** | Per town | Encrypted DB snapshots | Per-town bucket, per-town key |
| **Control-plane DB** | Fleet | Tenant registry, domains, versions, provisioning + ops audit, aggregated **non-PII** telemetry/cost | Never contains town request data or PII |
| **Host secret store** | Platform | Platform-managed secrets (§6) | Managed by host (Key Vault / Secret Manager / sealed secrets) |

Rule enforced in code: the app never sends town data to the panel; `/telemetry`
is metadata/counters only.

---

## 6. External connections — who handles what

### Configuration & payment responsibility
| Connection | Configured by | Paid by | Where it lives |
| :--- | :--- | :--- | :--- |
| GovTech integrations (SDL, Edmunds, GovPilot, Tyler, Accela, CivicPlus, Polimorphic, Open311) | **Town** | Town (vendor contract) | Town instance (encrypted creds) — already built |
| AI (Vertex/Azure OpenAI/Bedrock) | **Town** | **Town** (own key, direct-billed) | Town instance; **off until key entered** in managed mode |
| Translation | **Town** | Town | Town instance |
| Maps (Google Maps — unchanged) | **Town** | Town (Google Maps key) | Town instance |
| SMS / Email | **Town** | Town | Town instance |
| Database, Redis, object storage, compute, TLS/domains | **Host** | **Host** | Platform infra |
| Encryption key infra (KMS/HSM), secret store | **Host** | Host | Platform (per-town key) |
| Container images, migrations, patches | **Org** | Org (dev) | Published to registry |
| Staff identity (IdP — Auth0 / Entra / Okta via OIDC) | Host pattern; **Town or State** config | Host/State | Town instance (OIDC config) |

**Managed-mode policy:** cost-incurring town features stay **disabled until the
town supplies its own key**, so the host never absorbs a town's API bill. This
is what makes the proposal's "$2–$11/month, adjustable anytime" real.

---

## 7. Provider matrix — options per capability

We provide a **curated set** of adapters per capability (not "literally every
provider"), each selectable by config, with a sensible default per stack. Some
capabilities the **host** fixes per deployment; others the **town** chooses
(because the town pays).

| Capability | Pluggable? | Chosen by | Adapters we build | GCP-stack default | Azure-stack default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Identity** | **Yes** (OIDC-generic) | Host or Town | One OIDC adapter → **Auth0 · Microsoft Entra ID · Okta** (+ any OIDC IdP) | Auth0 | Entra ID |
| **AI** (2-level: provider, model) | **Yes** | **Town** | **Vertex AI** (Gemini **+ Claude**) · **AWS Bedrock** (Claude + others) · **Azure Government AI** (Azure OpenAI in gov regions) | Vertex / Gemini Flash-Lite | Azure Gov / GPT-4o-mini |
| **Translation** | **Yes** | Town | Google Cloud Translation · **Azure Translator** | Google | Azure |
| **Secrets store** | **Yes** | **Host** | Google Secret Manager · **Azure Key Vault** · DB-Fernet fallback | Secret Manager | Key Vault |
| **Key management (PII)** | **Yes** | **Host** | Google Cloud KMS · **Azure Key Vault Managed HSM** · Fernet fallback | Cloud KMS | Key Vault HSM |
| **Maps (geocoding + display)** | No (unchanged) | Town | **Google Maps** (as today) | Google Maps | Google Maps |
| **SMS** | Yes (exists) | Town | Twilio · generic HTTP | Twilio | Twilio |
| **Email** | Yes (exists) | Town | SMTP (any provider) | SMTP | SMTP |
| **Object storage** | Host infra | Host | S3-compatible · Azure Blob | GCS/S3 | Azure Blob |
| **Hosting/orchestration** | Host infra | Host | Kubernetes (any cloud) · Compose fleet | GKE | AKS |

Design notes:
- **AI is two-level** (`boundary → model`): pick the compliant boundary, then
  the model within it. Vertex covers **Gemini + Claude**; Bedrock covers
  **Claude** in an AWS boundary; Azure Government AI covers **Azure OpenAI**
  in gov regions. Town chooses and pays (own key). *Verify current Azure
  Government / GovCloud model availability before finalizing per-stack defaults.*
- **Translation, Secrets, KMS** each get an Azure adapter alongside the existing
  Google one; the **host** picks these to match its cloud.
- **Identity is pluggable via one generic OIDC adapter** (Auth0 / Entra ID /
  Okta / any OIDC IdP), chosen by the host or town; Auth0 stays the default so
  nothing changes for existing deployments. An M365 state can point staff SSO
  at Entra with config only.
- **Maps (Google Maps) is intentionally unchanged** — an Azure-hosted
  deployment still uses the existing Google Maps browser key (a light
  referrer-restricted key, not a cloud project).

---

## 8. Phased delivery plan

### Phase 0 — Security remediation ✅ (done)
Critical audit fixes landed (`SECRET_KEY`, PII/KMS, SSRF, auth bootstrap, PII
export, rate limits). Branch `claude/security-audit-fixes`.

### Phase 1 — App hosted-hooks + core upgrades (Repo A) — *start here*
- Hosted hooks: `MANAGED_MODE`, provisioning API, `/telemetry`, disable self-update in managed mode, version/migration stamping, lifecycle export/suspend/shred.
- Core upgrades (ship to ALL deployments): hash-chain `RequestAuditLog` (immutable audit) + verify endpoint; safety-flag surfacing / at-risk queue.
- Central-log PII scrubbing.
- **DoD:** a single instance can be provisioned entirely via API + env, runs migrations on boot, exposes telemetry, a town admin completes setup in-browser with infra hidden, and the immutable audit log + safety queue work for self-hosted and hosted alike.

### Phase 2 — Control-plane MVP (Repo B)
- Tenant registry + provisioner + one town end-to-end (Compose-fleet target first).
- **DoD:** panel provisions a new isolated town (DB + key + domain + deploy + onboarding email) in minutes; town data proven isolated.

### Phase 3 — Fleet operations (Repo B)
- Release manager (canary + migration gating + rollback), fleet dashboard, billing visibility, break-glass, suspend/offboard/shred.
- **DoD:** upgrade a cohort with auto-rollback; per-town cost visible; a town can be offboarded and crypto-shredded.

### Phase 4 — Provider abstraction (Repo A)
- Land the interfaces and ship the adapters: **Identity** — generic OIDC (Auth0 + Entra ID + Okta); **AI** — Vertex + Bedrock + Azure Government AI (two-level provider/model); **Translation** — Google + Azure; **Secrets** — Secret Manager + Key Vault; **KMS** — Cloud KMS + Key Vault Managed HSM.
- Maps (Google) unchanged.
- Each adapter ships with its **guided config card + field hints + Test-connection check** (§3.5), not just the backend.
- **DoD:** a non-technical admin can, entirely in the browser, point identity at Auth0/Entra/Okta, run AI on any of the three boundaries (with a model picker), and run translation/secrets/KMS on Google or Azure — no code changes, and the flow is at least as easy as today's Auth0/Google setup.

### Phase 5 — NJ production/compliance hardening
- StateRAMP / NJ SISM alignment; signed SSP/PIA/IR/DR; VPAT; OPRA workflow; records retention mapped to NJ DARM; SLA + RACI; k8s/GitOps target.
- **DoD:** package a state could take to an ATO; 3–5 town pilot live with success metrics.

---

## 9. Open decisions (must settle; detailed in HOSTED_MODEL_SCOPE.md §7)
1. **KMS ownership** — recommend host-provided shared HSM with per-town keys (crypto-shred, no per-town HSM floor).
2. **Cloud/provider default** — confirm NJ OIT's authorized cloud (Azure vs AWS GovCloud) → sets the default stack.
3. **Identity boundary** — commercial Auth0 (staff-only, free tier likely sufficient) vs gov-authorized IdP (Entra/Okta-Gov) if a state mandates it.
4. **Shared-key chargeback** — town-brings-own-key (recommended, no invoicing) vs metered chargeback.
5. **Data residency/region** per state.

---

## 10. Cross-cutting principles
- **Minimal product change** — keep the existing UX; maps (Google) stays as-is and Auth0 remains the identity default. Provider choice adds config options, not new surfaces.
- **Every provider is pre-built and point-and-click** — switching is config, never code; the setup UX must be as easy as or easier than today's Auth0/Google flow (guided cards, plain-language hints, Test-connection, auto-enable). Ship maximal defaults so the admin enters the fewest fields possible. See §3.5, §3.7.
- **Consistent premium + accessible design everywhere** — every new surface (including the orchestration panel) uses the app's glassmorphism design system via the shared `ui` primitives and stays WCAG 2.1 AA (keyboard, contrast, ARIA, reduced-motion). See §3.6.
- **Core upgrades benefit everyone** — genuine improvements (immutable audit log, safety-flag surfacing) ship to self-hosted and centralized alike, never gated to managed mode.
- **App never phones home with data** — panel is metadata-only.
- **Additive to the app** — standalone self-host stays first-class.
- **Managed-mode = least privilege for towns** — infra hidden, only what they own is editable.
- **Honest claims** — no proposal statement outruns shipped code.
</content>
