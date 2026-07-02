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

### 3.2 Proposal "STRENGTHEN" items (make the pitch fully truthful)
| Item | Work |
| :--- | :--- |
| Immutable request audit log | Extend the SHA-256 hash-chain (already on the auth `AuditLog`) to `RequestAuditLog`, so "immutable, tamper-evident" is literally true for OPRA. Add a verify endpoint. |
| State/county road detection | Ship the `routing_mode=road_based` line-layer detection end-to-end and load the **NJDOT + county road centerline** layer; resident on a state road is redirected to NJDOT instead of the town queue. |
| Safety-flag surfacing | AI already emits `safety_flags`; add prominent staff-dashboard surfacing + an at-risk queue so hazards don't sit unnoticed. |

### 3.3 Security hardening carryover (from the audit)
- Already remediated: `SECRET_KEY` enforcement, PII/KMS handling + `REQUIRE_KMS`, SSRF guard, auth-bootstrap hardening, opt-in PII export, comment authz, rate limits, `_flag` PII-share gate.
- Close for production: remove Docker-socket self-update in hosted mode (done via §3.1), **central-log PII scrubbing** (hard requirement once logs ship to a state sink), CSP tightening review, dependency pinning + failing CI on high-severity.

### 3.4 Provider abstraction layer (new seams — phased, see §8)
Define one interface per capability and select via config. Interfaces:
`IdentityProvider`, `AIProvider (provider, model)`, `TranslationProvider`,
`SecretStore`, `KeyManager`, `GeocodeProvider`, `MapDisplayProvider`,
`SmsProvider`, `EmailProvider`, `ObjectStore`. Existing services
(`vertex_ai_service`, `translation`, `secret_manager`, `encryption`,
`auth0_service`, gis/maps) become the first implementations behind these.

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
| Maps geocoding / display | **Town** | Town (or free Census) | Town instance |
| SMS / Email | **Town** | Town | Town instance |
| Database, Redis, object storage, compute, TLS/domains | **Host** | **Host** | Platform infra |
| Encryption key infra (KMS/HSM), secret store | **Host** | Host | Platform (per-town key) |
| Container images, migrations, patches | **Org** | Org (dev) | Published to registry |
| Staff identity (IdP) | Host pattern; **Town or State** config | Host/State | See §7 decision |

**Managed-mode policy:** cost-incurring town features stay **disabled until the
town supplies its own key**, so the host never absorbs a town's API bill. This
is what makes the proposal's "$2–$11/month, adjustable anytime" real.

---

## 7. Provider matrix — options per capability

We provide a **curated set** of adapters per capability (not "literally every
provider"), each selectable by config, with a sensible default per stack. Some
capabilities the **host** fixes per deployment; others the **town** chooses
(because the town pays).

| Capability | Pluggable? | Chosen by | Adapters we build | GCP-stack default | Azure-stack default | NJ recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Identity** | Yes (OIDC-generic) | Host or Town | One OIDC adapter → Auth0 / Entra ID / Okta | Auth0 | Entra ID | Per §7 decision (state IdP vs Auth0) |
| **AI** (2-level: provider, model) | Yes | **Town** | Vertex (Gemini **+ Claude**) · OpenAI-compatible (Azure OpenAI + OpenAI) · Bedrock (on demand) | Vertex / Gemini Flash-Lite | Azure OpenAI / GPT-4o-mini | Match state cloud; Gemini Flash-Lite cheapest |
| **Translation** | Yes | Town | Google Cloud Translation · Azure Translator | Google | Azure | Match AI stack |
| **Secrets store** | Yes | **Host** | Google Secret Manager · Azure Key Vault · DB-Fernet fallback | Secret Manager | Key Vault | Match host cloud |
| **Key management (PII)** | Yes | **Host** | Google Cloud KMS · Azure Key Vault Managed HSM · Fernet fallback | Cloud KMS | Key Vault HSM | Host-provided, per-town key, `REQUIRE_KMS` on |
| **Geocoding** | Yes | Town | **US Census (free/federal)** · Esri/NJGIN · Google · Azure Maps | Google or Census | Azure Maps or Census | **Census + NJGIN/Esri** (no forced 2nd cloud) |
| **Map display** | Yes (hard) | Town/Host | Google Maps JS (default) · MapLibre + Esri/Azure tiles | Google Maps | MapLibre+Azure/Esri | Esri (NJ already licenses it) |
| **SMS** | Yes | Town | Twilio · generic HTTP (both exist) | Twilio | Twilio | Town choice |
| **Email** | Yes | Town | SMTP (any provider) · optional SendGrid / Graph | SMTP | SMTP/Graph | Town/state relay |
| **Object storage** | Yes | Host | S3-compatible (exists) · Azure Blob | GCS/S3 | Azure Blob | Match host cloud |
| **Hosting/orchestration** | Yes | Host | Kubernetes (any cloud) · Compose fleet | GKE | AKS | Match state cloud |

Design notes: **AI is two-level** (`boundary → model`) so one Vertex adapter
covers Gemini *and* Claude, and one OpenAI-compatible adapter covers Azure
OpenAI *and* OpenAI. **Geocoding defaults to the free federal Census service**
so no town is forced into a second cloud just for maps. **Map display** is the
only genuinely hard swap (front-end SDK) — Google Maps stays the light default
(a single referrer-restricted browser key, not a cloud project); Esri is the
first alternative because NJ already runs it.

---

## 8. Phased delivery plan

### Phase 0 — Security remediation ✅ (done)
Critical audit fixes landed (`SECRET_KEY`, PII/KMS, SSRF, auth bootstrap, PII
export, rate limits). Branch `claude/security-audit-fixes`.

### Phase 1 — App hosted-hooks + STRENGTHEN (Repo A) — *start here*
- `MANAGED_MODE`, provisioning API, `/telemetry`, disable self-update in managed mode, version/migration stamping, lifecycle export/suspend/shred hooks.
- STRENGTHEN: hash-chain `RequestAuditLog`; road-based detection + NJDOT layer; safety-flag surfacing.
- Central-log PII scrubbing.
- **DoD:** a single instance can be provisioned entirely via API + env, runs migrations on boot, exposes telemetry, and a town admin completes setup in-browser with infra hidden.

### Phase 2 — Control-plane MVP (Repo B)
- Tenant registry + provisioner + one town end-to-end (Compose-fleet target first).
- **DoD:** panel provisions a new isolated town (DB + key + domain + deploy + onboarding email) in minutes; town data proven isolated.

### Phase 3 — Fleet operations (Repo B)
- Release manager (canary + migration gating + rollback), fleet dashboard, billing visibility, break-glass, suspend/offboard/shred.
- **DoD:** upgrade a cohort with auto-rollback; per-town cost visible; a town can be offboarded and crypto-shredded.

### Phase 4 — Provider abstraction (Repo A)
- Land the interfaces; ship Vertex + OpenAI-compatible (AI), OIDC-generic (Auth0+Entra), Secret/Key (GCP+Azure), Geocode (Census+Esri). Map-display (MapLibre+Esri) as its own sub-task.
- **DoD:** a town/deployment can run a coherent Azure or GCP stack with no forced second cloud.

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
- **No forced second cloud** — every stack has a coherent single-vendor path.
- **App never phones home with data** — panel is metadata-only.
- **Additive to the app** — standalone self-host stays first-class.
- **Managed-mode = least privilege for towns** — infra hidden, only what they own is editable.
- **Honest claims** — no proposal statement outruns shipped code (see STRENGTHEN items).
</content>
