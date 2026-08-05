# GovTech Integrations — Hardening & Correct-Wiring Spec

Status: **open** · Written 2026-08-05 from a full review of the "Connect Your
Other Town Systems" feature (backend + frontend). Companion to
[INTEGRATIONS.md](INTEGRATIONS.md), which describes the intended design; this
document lists where the implementation diverges from it and defines the work
to close each gap.

Scope of the review: `backend/app/api/integrations.py`,
`backend/app/integrations/**`, `backend/app/tasks/integrations.py`,
`backend/app/services/{connector_health,connector_alerts,connector_verification,circuit_breaker}.py`,
`frontend/src/components/GovtechIntegrations.tsx`,
`frontend/src/components/SetupIntegrationsPage.tsx`, `frontend/src/services/api.ts`.

Ground rules for whoever implements this:

- Work package by package, in the order below (WP1 is the highest-severity
  cluster). Each package should be a coherent commit (or small series) with
  tests.
- Line numbers were accurate at review time (branch
  `claude/connect-towns-integrations-review-73afad`); re-locate by the quoted
  code if they have drifted.
- Several existing tests **mask** bugs by mocking collaborators with the wrong
  signature. When a fix changes behavior, fix the test to exercise the real
  signature/object — do not re-mock around it.
- Do not change the external webhook payload contract or the admin API
  response shapes except where a package explicitly says to add a field.

---

## WP1 — Make the health/alert loop real for govtech connectors

The feature's monitoring story is currently mostly fictional for these
connectors: health rows are written only on resident-report pushes, the daily
sweep never tests them, mutes don't hold, and one alert path crashes.

### 1.1 Daily sweep must test configured integrations

`backend/app/services/connector_verification.py:56-58` builds its worklist
from `_CAPABILITY_TESTS` in `app/api/system.py:1204-1213` (ai, translation,
identity, maps, email, sms, kms, redaction only). Nothing enumerates
`IntegrationConfig` rows, despite the module docstring ("Test every configured
connector") and the `FRESH_FOR` rationale in
`connector_health.py:43-50` assuming it does.

**Fix:** in the sweep, select all enabled `IntegrationConfig` rows, build each
connector via `build_connector_for` (`integrations/registry.py:291-302`), run
`test_connection()` through `guard()` (`services/circuit_breaker.py:193`) with
connector name `govtech:<platform>` and `db` supplied, so success/failure
lands in `ConnectorHealth` exactly like the push paths at
`tasks/integrations.py:365` and `:422`.

**Acceptance:** an enabled integration whose vendor is down flips to
`BROKEN`/`AT_RISK` within one sweep with zero resident traffic; a healthy one
never goes `STALE` (fixes the false "Accela may stop working" email after 3
quiet days — staleness classifier at `connector_health.py:129-140`).

### 1.2 `POST /{id}/test` must feed health and reset the breaker

`api/integrations.py:264-285` writes an `IntegrationSyncLog` only. It never
calls `connector_health.record_success/record_failure` and never calls
`breaker.reset()` — even though `circuit_breaker.py:173-176` documents that an
admin pressing Test resets the breaker (grep confirms zero callers of
`breaker.reset` outside the module and tests).

**Fix:** run the test through `guard(f"govtech:{platform}", ..., db=db)`; on
success additionally call `breaker.reset(name)` so a fixed credential takes
effect immediately instead of waiting out the cooldown. Handle `CircuitOpen`
by resetting first (an explicit admin test is the sanctioned probe).

**Acceptance:** after a failing period, one passing Test flips the admin badge
to healthy and the next push is attempted immediately.

### 1.3 Mutes must hold (and escalations must break through)

`connector_health.py:97` declares `alert_muted_until` on the `Health`
dataclass but not `alert_muted_level`, and `to_health`
(`connector_health.py:143-162`) never copies it. `plan()` reads
`getattr(h, "alert_muted_level", None)` (`connector_alerts.py:247`) → always
`None` → `RANK.get(None, RANK[BROKEN])` (`connector_alerts.py:172`) → the
mute check degenerates. The documented invariant ("an escalation breaks
through a mute", `connector_alerts.py:157-161`, `models.py:1016-1021`) does
not hold.

**Fix:** add `alert_muted_level` to the dataclass and copy it in `to_health`.
Fix `tests/test_connector_alerts.py:498`, which passes an ad-hoc object that
already has the attribute (why this was never caught) — build the `Health` via
`to_health` from a real row instead.

### 1.4 Hourly probe alert dispatch crashes

`connector_verification.py:189-190` calls `await alerts(db)`, but the injected
callable is `connector_alerts.dispatch` (`tasks/connector_checks.py:57`) whose
signature requires `healths` (`connector_alerts.py:404-408`). Guaranteed
`TypeError`; caught at `tasks/connector_checks.py:60-63` and logged as
"hourly system probe could not run". Probe readings are recorded, but no probe
alert email has ever been sent.

**Fix:** load the health snapshot (as `notify` does at
`connector_verification.py:116-121`) and pass `healths=` to `dispatch`. Fix
`tests/test_system_probe_alerts.py:76`, which stubs `async def alerts(db)` —
matching the buggy call site rather than the real dispatcher.

### 1.5 `test_connection` must actually verify credentials

Only Accela authenticates (`connectors/accela.py:123-130`). The other three
return `{"ok": True}` against endpoints that work anonymously:

- `generic_rest.py:177-184` — GET with auth headers added only if a key exists
  (`:92-101`);
- `open311.py:71-78` — `/services.json`, anonymous on most GeoReport servers;
- `seeclickfix.py:68-78` — public `/issues`, `_auth_kwargs()` returns `{}`
  without creds (`:43-48`).

**Fix:** where the platform has an authenticated endpoint, hit it. Where it
genuinely doesn't (Open311 without an api_key), return a distinct result such
as `{"ok": true, "verified": false, "detail": "Server reachable; credentials
are only exercised on the first push."}` and surface that wording in the UI
instead of "Connected".

---

## WP2 — Data integrity & deployment correctness

### 2.1 Missing migration for `documents_pushed_count`

Declared at `models.py:805`, written/read at
`tasks/integrations.py:226,237,243`, present only in the ad-hoc
`init_db.py:183` DDL. Migration `20260701_1400_b2c3d4e5f6a7` adds only
`pushed_comment_ids` and `documents_pushed`. An Alembic-only deployment gets
`UndefinedColumn` on the first document push.

**Fix:** new Alembic migration adding the column (nullable int, server default
0 to match the model). While there: `documents_pushed` (bool, set at
`tasks/integrations.py:230,238`) is never read anywhere — either drop it
(model + migration) or start using it; don't leave a dead column.

### 2.2 Unique constraint on `IntegrationConfig.platform`

`models.py:737` is `index=True` only (migration
`20260701_0900_a1b2c3d4e5f6` creates a non-unique index), while
`api/integrations.py:150-154` does SELECT-then-INSERT. Concurrent creates
produce duplicate rows and every push loop pushes twice.

**Fix:** migration converting to a unique index; catch `IntegrityError` in the
create endpoint and return the existing 409.

### 2.3 Close the pull-window race

`tasks/integrations.py:521` sets `last_sync_at = now()` *after* the fetch —
vendor updates that land during the fetch are skipped forever. Every connector
already returns `ExternalRecord.updated_at` (`accela.py:111`, `open311.py:63`,
`generic_rest.py:150`, `seeclickfix.py:57`) and nothing reads it.

**Fix:** capture `since_candidate = now()` **before** calling the connector,
or better, advance `last_sync_at` to `max(record.updated_at)` of the processed
batch. Add a small overlap (e.g. re-query from `last_sync_at - 5min`) since
these systems' timestamps are not transactionally ordered; existing link
lookups make replays idempotent.

### 2.4 Accela pull pagination and time granularity

`accela.py:190` sends `updateDateFrom=since.strftime("%Y-%m-%d")` with
`limit: 100` and no offset loop — day-granular (refetches the whole day every
15 min) and silently drops records past the 100th. `pull_assets` in the same
file already pages correctly (`accela.py:278-308`); mirror that pattern, and
use Accela's datetime-capable parameter if available for the API version.

### 2.5 Rollback + commit discipline in push tasks

- `push_request_to_integrations` (`tasks/integrations.py:386-389`) and
  `push_status_to_integrations` (`:435-439`) lack the `await db.rollback()`
  that the other three tasks have (`:531`, `:647`, `:783`). A DB-level failure
  leaves the session in `PendingRollbackError`, so `_log`'s commit (`:315`)
  raises and aborts the remaining integrations in the loop. Add the rollback.
- `connector_health.record_success/record_failure` call `db.commit()`
  (`connector_health.py:248,257,310,318`) from inside per-integration loops,
  committing partially-applied link mutations mid-iteration (visible in
  `push_status_to_integrations`). Restructure so health recording uses its own
  session (or defers commit) rather than committing the caller's transaction.
- `connector_health._row` (`connector_health.py:214-227`) SELECT-then-add
  races the unique index (`models.py:979`); on conflict the exception is
  swallowed (`:258-260`) and the data point is lost. Use an upsert
  (`ON CONFLICT`) instead.

### 2.6 Vault hygiene

- `delete_integration` (`api/integrations.py:214-225`) never deletes the
  `INTEGRATION_<PLATFORM>_<FIELD>` secrets written by `store_credentials`
  (`integrations/credentials.py:48-107`). Delete them (best-effort, logged) on
  disconnect.
- `IntegrationCreate.credentials` (`api/integrations.py:49`) is unvalidated —
  reject keys not present in the platform's `credential_fields` so admins
  can't write arbitrary `INTEGRATION_*` vault keys. Apply the same allowlist
  to `config` keys against `config_fields`.
- `credentials_vaulted` (`api/integrations.py:101-104`) uses `any(...)` —
  report the true state (`all` vaulted vs partial) so the UI's "stored in your
  Secret Manager" trust line isn't over-claimed.
- Silent decrypt failure: `models.py:769-770` returns `{}` on any exception —
  log at ERROR with the integration id (never the ciphertext) so a rotated
  `SECRET_KEY` doesn't masquerade as "someone deleted the credentials".
- Distinguish "vault unreachable" from "field blank": `resolve_credentials`
  omits unresolvable refs (`credentials.py:144-150`) and the connector then
  says "credentials missing", which `_friendly_test_error`
  (`api/integrations.py:258-259`) turns into "go back and fill them in" —
  wrong advice. Have `resolve_credentials` raise/return a distinct marker for
  resolution failure and map it to its own friendly message.

---

## WP3 — Endpoint semantics

### 3.1 Scope "Sync now" to the clicked integration

`api/integrations.py:288-306` validates `integration_id` then enqueues the
**global** `pull_integration_updates()` / `pull_integration_comments()`
(`:303-304`). Add an optional `integration_id` parameter to those tasks (loop
filter) and pass it. Also fix the enqueue result handling: currently
`enqueue(a) or enqueue(b)` semantics mean a first-enqueue failure skips the
second, and a second-enqueue failure returns 503 after a job already started.
Enqueue both, then report accurately.

### 3.2 Asset sync must not silently enroll in nightly sync

`api/integrations.py:325-327` sets `config["sync_assets"] = True` as a side
effect of the one-off button, permanently opting the integration into the
daily beat job (`tasks/integrations.py:744`) with no UI indication and no way
back. Make the one-off run not mutate config; expose `sync_assets` as an
explicit config field in the catalog/wizard instead.

### 3.3 Webhook hardening

`api/integrations.py:426-448`: token compared in SQL (`:443`) — fetch by
platform and compare with `secrets.compare_digest`; honor `sync_direction`
(a push-only integration currently still accepts inbound creates); consider
per-token rather than per-IP rate limiting (`:427`) since one vendor egress IP
serves many events. Keep the token-in-path contract (vendors are already
configured with it) but note in docs that the URL appears in proxy logs, and
add a "regenerate webhook token" admin action.

### 3.4 Honest capabilities for `generic_rest`

`generic_rest.py:64` claims `comments`, `documents`, `assets`, `work_orders`
unconditionally, so `pull_integration_comments` (`tasks/integrations.py:673`)
and `sync_integration_assets` (`:748`) poll vendors that lack those endpoints
and write an error row to `integration_sync_logs` every 15 minutes. Derive
capabilities from which endpoint paths the admin actually configured (only
claim `comments` if `comments_path` is set, etc.).

---

## WP4 — Frontend: truthful feedback and safer setup

All in `frontend/src/components/GovtechIntegrations.tsx` unless noted.

1. **Errors visible inside the modal.** `saveWizard` writes `error` (`:159`)
   but it renders only behind the modal (`:333-337`); a failed save makes
   "Save & check the connection" appear to do nothing (`goToFinish`
   early-return at `:187-188`). Render errors inside the wizard; same for
   `handleDelete` (`:252`).
2. **Required credential validation.** `requiredMissing` (`:127-133`) checks
   `config_fields` only, and no registry `credential_fields` carry
   `required` — an all-blank Accela save succeeds. Mark required credential
   fields in the registry (`integrations/registry.py`) and enforce client-side
   (skip enforcement when a saved value exists, i.e. `savedHint` present).
3. **Per-connector busy state.** `busy` is one global string (`:46`) and every
   card disables on `busy !== null` (`:484,:488,:493,:504`). Key by
   integration id.
4. **Refresh after actions.** `handleCardTest` (`:208-218`), `handleSync`,
   `handleSyncAssets` (`:220-242`) never `load()`; with WP1.2 the test result
   changes server state, so reload configs (and logs if the drawer is open)
   after each action. Show a syncing label on "Check for updates" (it's the
   only button without one, `:488-490`).
5. **Show the real error.** `last_sync_error` is fetched (`api.ts:79`) and
   never rendered — the card shows a generic "hit a problem" (`:450-452`).
   Render it (truncated) on the card and in the Activity drawer.
6. **Allow clearing config values.** Backend merges config
   (`api/integrations.py:184-185`) and the frontend skips empty strings
   (`:142`), so a wrong `jurisdiction_id` can never be blanked. Decide a
   convention (send explicit `null` to delete; backend removes the key) and
   implement both sides.
7. **Gate the card toggle on health.** The toggle (`:502-514`) enables without
   any test, contradicting the wizard promise at `:791-792`. Minimum: when
   enabling a connector whose last test/health is failing, require an explicit
   confirm.
8. **Persistent webhook URL + vendor email.** Both are only reachable in the
   wizard intro / success screen (`:744-763`, intro only via Back `:699`).
   Add a copyable webhook URL and "view vendor request email" to the expanded
   card.
9. **Small fixes:** empty-state flash before first load (`:353-357` renders
   `No platforms match ""` — add a loading branch); `setSyncChoice` called
   during render (`:649` — move to an effect); dead `testStarted` state
   (`:68,:122,:190`); blank `finish` step when `runFinishTest` early-returns
   (`:721-805`); double `load()` in `handleDelete` (`:249-250`);
   `window.confirm` at `:245` → use `useDialog().confirm`; `copyText`
   unhandled rejection (`:105-109`); stale "11 platforms" comment (`:53`);
   `integration_mode` union missing vs. dead `generic` label
   (`api.ts:45` / `:21` — remove the dead label); subtitle count while
   searching (`:319`); section missing `id` for the status rail (`:316` vs
   `SetupIntegrationsPage.tsx:1039`); step dots `aria-hidden` with no textual
   step indicator (`:554-558`).
10. **Roll govtech connectors into the page-level health/progress.**
    `SetupIntegrationsPage.tsx:378-383` builds the "N not working" badge from
    `GET /api/system/connectors/health`; after WP1 the `govtech:*` rows will
    be meaningful — include them (and consider counting configured town
    systems in the Setup Progress tracker at `:516-527`).
11. **Expose request links.** `GET /api/integrations/requests/{id}/links`
    (`api/integrations.py:391`) has no client function or caller — staff can't
    see which external records a request is linked to. Add it to `api.ts` and
    surface linked-record IDs (with external status) on the staff request
    detail view.
12. `SetupIntegrationsPage.tsx:391` calls `fetch('/api/system/config')` raw,
    bypassing `ApiClient.request` (no auth header, no 401 handling). Route it
    through the client.

---

## Out of scope (tracked separately, do not do here)

- New connector types (ArcGIS feature-service hub, email intake/notification
  connector, CSV/SFTP exchange) — strategic follow-ups, not wiring fixes.
- Multi-tenancy: the unscoped queries are **correct** for this single-tenant
  deployment; do not add tenant columns.
- Removing `connectors/vendors.py` / `TylerConnector` vestige and
  `BaseConnector.allow_internal_hosts` — harmless; fold into any adjacent
  refactor only.

## Definition of done

- All WP1–WP4 items implemented with tests; the two signature-mismatch tests
  (`tests/test_connector_alerts.py:498`, `tests/test_system_probe_alerts.py:76`)
  rewritten to exercise real collaborators.
- `alembic upgrade head` from the previous revision succeeds on a copy of a
  production-shaped DB; a document push works on an Alembic-only schema.
- Full backend test suite and frontend build/tests pass.
- [INTEGRATIONS.md](INTEGRATIONS.md) updated where behavior changed (test
  semantics, sync-now scoping, sync_assets opt-in, webhook token regeneration).
