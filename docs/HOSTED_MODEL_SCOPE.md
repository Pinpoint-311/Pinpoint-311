# State-Hosted Multi-Tenant Model — Change Scope

> **Anchored to the NJIA/DCA centralized-hosting proposal.** Every commitment
> in that proposal maps to a build status below. Legend: **EXISTS** (works
> today) · **HOSTED** (needs the multi-tenant/managed-mode tooling this doc
> scopes) · **STRENGTHEN** (partially built; needs work to fully match the
> claim) · **CONFIG/DATA** (works but needs NJ data loaded) · **ABSTRACT**
> (provider-adaptability, phased).

## 0. Proposal commitment → build status

| Proposal commitment | Status | Notes / build task |
| :--- | :--- | :--- |
| Sub-60s reporting, no account, SMS/email magic-link tracking | EXISTS | — |
| 109-language end-to-end (report → description → notifications) | EXISTS | — |
| Photo + GPS or asset-based location (click hydrant/light/park) | EXISTS | Map layers + asset match |
| Early-detection value framing | EXISTS | Narrative only |
| Single staff view: weather + history + geospatial context | EXISTS | `weather_service`, spatial context |
| AI augments, human-approved (staff-reviewed priority/classification) | EXISTS | `manual_priority_score`, accept-AI-priority; AI never auto-sets legal hold |
| Conversational analytics assistant (plain-language queries) | EXISTS | `/analytics-chat` (now rate-limited) |
| Automated safety flagging surfaced for immediate attention | STRENGTHEN | AI emits `safety_flags`; confirm/boost prominent surfacing in staff UI |
| OPRA-export-ready **immutable**, timestamped audit log, NJ retention | STRENGTHEN | Timestamped append + NJ retention EXIST; **`RequestAuditLog` is not hash-chained** (the auth `AuditLog` is). Extend the hash-chain to request actions to truthfully claim "immutable," or soften wording. |
| Session-based non-emergency disclaimer + immutable trail; WCAG 2.1 AA | EXISTS | `DisclaimerAcknowledgment`; accessibility CI |
| State/county road detection → redirect to NJDOT/correct agency | DEFERRED | Out of scope for now (routing_mode=road_based exists but the NJDOT layer + detection work is parked) |
| Open311 v2 compatibility | EXISTS | `/api/open311/v2` |
| Research Suite: 60+ anonymized fields | EXISTS | `research.py` (note prior audit: regex redaction should be strengthened) |
| One server hosts many **isolated** municipal instances (no bleed) | HOSTED | Silo model; the multi-tenant tooling this doc scopes (§3–§4) |
| Browser-based, afternoon, no-command-line town setup | HOSTED + EXISTS | Setup/integration wizards EXIST; add `managed_mode` (hide infra) + provisioning handoff so a town does only config |
| Per-town cost $2–$11/mo via town's own cloud keys | HOSTED | `managed_mode` BYO-key policy (features off until town supplies key); cost tracker EXISTS for visibility |
| Adding a town takes minutes | HOSTED | Control-plane provisioner (new repo) |
| Host deploys updates (not the town) | HOSTED | Disable in-app self-update in managed mode; panel-driven rollouts |
| Org/host/municipality responsibility split | HOSTED | Matches §1 below |
| "Not tied to a cloud; Azure = config change" | ABSTRACT | Provider abstraction (§3.9); honest today = "adaptable," full Azure path is phased work |
| Security: internal audit done + remediated; 3rd-party welcome | STRENGTHEN | Internal audit + critical fixes DONE; close remaining hardening (remove docker-socket self-update in hosted mode, central-log PII scrubbing) before production |

**Reads for the pitch:** the resident/staff/state feature set is real today; the
"multi-tenant deployment tooling in development" line in the proposal is
accurate and is precisely §3–§4 here. Two genuine upgrades ship to **all**
deployments (self-hosted and centralized): the **immutable (hash-chained)
request audit log** to justify the OPRA claim, and **safety-flag surfacing**.
NJDOT road detection is **deferred**. Security wording should read "internal
audit completed and remediated; hardening underway," not "clean."

---



Scoping document for running Pinpoint 311 as a **centrally state-hosted,
instance-per-jurisdiction (silo) platform** driven by an external
**orchestration panel** (separate repo).

This is a scope/plan, not an implementation. It enumerates every change needed
in the **app repo** (the per-town data-plane unit) and everything that belongs
in the **orchestration panel** (the control plane).

---

## 1. Responsibility model (who owns what)

| Party | Owns | Pays for | Never does |
| :--- | :--- | :--- | :--- |
| **Pinpoint 311 (org)** | Code, versioned container images, DB migrations, security patches, min-supported config contract | Its own development | Touch town data or hosting |
| **State** | Orchestration panel + all infra: compute, DB, storage, network, TLS/domains, backups, monitoring; provisioning, rollouts, break-glass support | Hosting/infra | Casually access resident PII (break-glass only, audited) |
| **Jurisdiction (town)** | Branding, service catalog, routing, staff & IdP, govtech connections, **its own external API keys** | **Its own API usage** (AI, Maps, Translation, SMS, email) + vendor integrations | Manage servers, DNS, or upgrades |

Isolation model: **silo** — each town is a full app instance with its own
database, `SECRET_KEY`, KMS key, object-storage prefix, and network namespace.
Cross-town data bleed is architecturally impossible because there is no shared
data store. The only shared surface is the panel, which handles **metadata
only** — never town data.

---

## 2. The secrets/config split (the crux of the model)

Every configurable value falls into one of two buckets. This split drives
`managed_mode` enforcement and who-pays.

### Platform-managed (state, injected by the panel — hidden/locked in the town UI)
- `DATABASE_URL`, `REDIS_URL`
- `SECRET_KEY` (unique per town — generated by the panel)
- KMS infrastructure references (`GOOGLE_CLOUD_PROJECT`/keyring or Azure Key Vault) *if the state provides encryption infra* — see §7 open question
- Backup storage (`BACKUP_S3_*`) — per-town encrypted bucket
- `DOMAIN` / allowed origins / TLS (state ingress terminates)
- Sentry / central telemetry DSN

### Tenant-managed (town configures **and pays for** — editable in the town UI)
- AI provider: `GOOGLE_CLOUD_PROJECT`+Vertex **or** Azure OpenAI keys → **billed directly to the town**
- `GOOGLE_MAPS_API_KEY` (or Azure Maps / Esri)
- Translation API key
- SMS (`TWILIO_*` / HTTP), SMTP email
- All govtech integration credentials (Accela, Tyler, SDL, …) — already per-instance & encrypted

**Billing consequence:** because tenant-managed keys are the town's own cloud
credentials, usage is billed directly by Google/Microsoft to that town — no
invoicing/chargeback needed. The app's existing `ApiUsageRecord`/cost tracker
becomes a *visibility* tool (town sees its own spend; panel sees a read-only
rollup), not a billing system. **Policy: in managed mode, cost-incurring
features stay OFF until the town supplies its own key**, so the state never
accidentally absorbs a town's API bill.

*(Optional future: shared-key + chargeback mode — panel meters per-town usage
and invoices. Larger effort; not required for the stated model.)*

---

## 3. App-repo changes (the per-town unit)

### 3.1 Managed mode
- Add `MANAGED_MODE` flag (config).
- When on: the secrets API rejects writes to **platform-managed** keys (§2) with 403; town UI hides infra/server/backup/domain settings and shows "Managed by your state" placeholders.
- Tenant-managed settings + integrations + branding remain fully editable.

### 3.2 Non-interactive provisioning
- Add a **provisioning API** authenticated by a per-instance `PROVISIONING_TOKEN` (constant-time compare; only active when set), callable by the panel to: set township name, set external domain, create/assign the initial admin, and return a **one-time admin onboarding link**.
- Replaces the interactive bootstrap flow in hosted mode (bootstrap stays for standalone self-host).

### 3.3 Disable in-app self-update (resolves the top infra audit finding)
- The current `/api/system/update` runs git pull + docker compose via a mounted Docker socket — the single biggest infra risk. In managed mode this must be **disabled**; upgrades come only from the panel (org publishes image → panel rolls out). Remove the socket mount from the hosted deploy manifests.

### 3.4 Migrations on boot
- App must run Alembic migrations idempotently on startup so panel-driven image bumps auto-migrate each town. Migrations must be **backward-compatible** (expand/contract pattern) for zero-downtime canary rollouts.
- Stamp the running **build/version + min DB revision** into the health endpoint so the panel can detect drift and gate rollouts.

### 3.5 PII-safe telemetry endpoint
- Add `GET /telemetry` (token-auth, panel-only) returning **metadata only**: version, uptime summary, request counts by status, integration health counts, API-usage/cost totals. **No resident data, ever.**
- Harden logging: central log shipping must be PII-scrubbed (the audit already flagged PII in some log lines — this becomes a hard requirement in hosted mode).

### 3.6 Identity
- Keep per-town staff IdP (Auth0/Entra) tenant-managed.
- Add support for a **state ops break-glass** access path: panel-issued, time-boxed, audited impersonation — distinct from town staff login, and logged in the town's audit trail.

### 3.7 Data-isolation hardening (mostly verification, not new code)
- Confirm no cross-tenant global state; Redis/object storage already per-instance.
- Confirm the app never phones home with data (telemetry is metadata-only).
- Per-town object-storage prefix/bucket for uploads.

### 3.8 Lifecycle hooks
- **Export** endpoint (full town data export for offboarding / open-records).
- **Decommission** hook: on offboard, the panel destroys the town's KMS key → crypto-shred (data unrecoverable) — strong deletion/compliance story.
- **Suspend/resume**: honor a panel-set "suspended" state (read-only or offline) without deleting.

### 3.9 Config-driven provider abstraction (optional, ties to Google-vs-Microsoft)
- Behind the existing seams (`encryption`, `secret_manager`, `vertex_ai_service`, `translation`, `auth0_service`, maps), allow per-deployment provider selection so an M365 state can pick Entra + Key Vault + Azure OpenAI. Maps (Google → Esri) is the hardest swap.

---

## 4. Orchestration panel (new repo) responsibilities

- **Tenant registry** — town, subdomain/custom domain, region, plan, status, running version, contacts. Metadata only.
- **Provisioner** — per town: create DB, generate `SECRET_KEY`, create/assign KMS key, allocate storage bucket, set DNS, request TLS, deploy app image @ version, call the app's provisioning API to set township+admin, email onboarding link.
- **Release management** — org publishes a versioned image → panel schedules **canary rollout** across the fleet, runs migrations, watches health, auto-rolls-back on failure. Enforces min-DB-revision compatibility.
- **Fleet dashboard** — health/version/cost aggregation, drift detection, per-town status, integration health across all towns.
- **Billing visibility** — aggregate each town's API usage/cost (from `/telemetry`) for the state and per-town views.
- **Break-glass support** — audited, time-boxed access into a town for the org/state to assist.
- **Secrets brokering** — only for **platform-managed** secrets (DB creds, `SECRET_KEY`, KMS refs, backup creds). Tenant-managed keys never touch the panel — the town enters them in its own instance.
- **Compliance** — central audit of all provisioning/rollout/support actions; tenant inventory as the authorization-boundary record (StateRAMP/FedRAMP).

---

## 5. Deployment shape

- **Target:** Kubernetes, one Helm release (or namespace) per town on a shared cluster, driven by GitOps (Argo/Flux). Panel commits a tenant manifest → GitOps reconciles → canary upgrades are trivial.
- **MVP shortcut:** panel renders per-town Compose stacks on managed hosts, graduate to k8s later.
- App ships as **versioned container images** the panel deploys — panel depends on the app by image tag, not source.
- TLS: wildcard `*.311.state.gov` via cert-manager/Caddy, plus on-demand ACME for towns that want a custom domain.

---

## 6. Cost structure (matches the responsibility split)

- **Org:** development only (no runtime cost).
- **State:** compute, DB cluster, storage, network, TLS, backups, monitoring, the panel. Favor **pay-per-use** infra and avoid per-tenant fixed floors (e.g., share one HSM pool with per-town keys rather than an HSM pool per town — see §7).
- **Town:** its own AI/Maps/Translation/SMS/email keys (billed directly) + vendor integration costs.

---

## 7. Open decisions to settle before building

1. **KMS ownership.** Does the *state* provide PII-encryption infra (one shared HSM/Key Vault with a per-town key — cheaper, state-managed), or does each *town* bring its own GCP project/Key Vault (town-managed, ties to their AI project)? Recommendation: **state-provided shared HSM with per-town keys** (crypto-shred on offboard, no per-town HSM floor). Set `REQUIRE_KMS=true` per tenant.
2. **Provider per state.** Google-native vs Microsoft/Entra — decide whether provider abstraction (§3.9) is in-scope for v1 or deferred.
3. **Identity boundary.** Will states accept a commercial IdP (Auth0 free tier) for staff that can reach PII, or require a gov-authorized IdP (Okta-for-Gov / Entra in Azure Gov)? Decides the auth layer.
4. **Shared-key chargeback.** Is "town brings own key" (recommended, no invoicing) sufficient, or is shared-key metering+billing required?
5. **Data residency / region** per town.

---

## 8. Rough sequencing

1. Land app hooks: `managed_mode`, provisioning API, `/telemetry`, disable self-update in managed mode, version stamping. *(Additive, testable in the existing app.)*
2. Stand up the panel: tenant registry + provisioner + one manual town end-to-end.
3. Release management (canary rollouts + migration gating).
4. Billing visibility + break-glass support + lifecycle (suspend/offboard/shred).
5. Provider abstraction (if a Microsoft state is in scope).
</content>
