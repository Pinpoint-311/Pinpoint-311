# GovTech Platform Integrations

Pinpoint 311 ships with a pluggable integration layer that connects it end-to-end
with the municipal systems of record most governments already run. Connections
are configured entirely from the Admin Console (**Setup & Integration → GovTech
Platform Connections**) — no code changes or redeploys.

## How it works

```
Resident submits request
        │
        ▼
Pinpoint 311 ──(push, on submit)──────────► External platform (record created)
        │                                          │
Staff updates status ──(push_status)──────────────┤
        │                                          │
        ◄──(pull, every 15 min via Celery Beat)────┘  status changes mirrored back
        ▲
        └──(inbound webhook)◄── platform-originated intake (e.g. Polimorphic AI front desk)
```

- **Push** — when a request is submitted, a Celery task pushes it to every
  enabled integration and stores the returned external ID as an
  `integration_link`. Embedded photos are then uploaded to the external record
  through the platform's document/attachment API where supported.
- **Push status** — when staff change a request's status, the change is
  mirrored to every linked platform record.
- **Comments (two-way)** — external-visibility comments (staff or resident)
  are posted onto the linked platform record; new comments made on the
  platform side are imported into the request's public comment thread every
  15 minutes. Echo protection ensures a comment never bounces back and forth.
- **Pull** — a Celery Beat job polls each pull-enabled platform every 15
  minutes; external status changes are applied to the linked local request and
  recorded in the request's audit log (actor type `integration`). With
  `import_new_records: true`, records that originate on the platform are
  imported as new Pinpoint requests (mapped via `service_code_map`).
- **Asset management** — a daily Beat job (or the **Sync Assets** button)
  mirrors the platform's asset inventory (hydrants, streetlights, signs…)
  into a Pinpoint map layer as GeoJSON points, so residents can attach reports
  to the exact asset and staff see asset-linked request history. The request's
  `matched_asset` is included in outbound pushes.
- **Inbound webhook** — each connection gets a unique tokenized URL
  (`/api/integrations/webhook/{platform}/{token}`). Platforms POST a
  normalized JSON payload to create requests in Pinpoint or update ones they
  originated. Repeat posts with the same `external_id` become status updates,
  and a `comments` array attaches comments in the same call.

All sync activity is logged to `integration_sync_logs` and visible per-platform
in the admin UI. Sync failures never block the core request lifecycle.

### Privacy

- Reporter PII (name, email, phone) is **not** shared with external platforms
  unless the integration's config sets `share_pii: true`.
- Embedded photos are never sent inline in JSON payloads; they are uploaded
  through the platform's document API where one exists, otherwise only
  `http(s)` media URLs are shared.
- Vendor credentials are encrypted at rest (Fernet derived from `SECRET_KEY`)
  and are never returned by the API after being saved.

## Supported platforms

| Platform | Vendor | Connection type | Push | Status out | Pull | Comments | Photos | Assets |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Accela** | Accela Civic Platform | Public API (Construct API v4, OAuth2) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Tyler Technologies** | Tyler 311 / MyCivic / EnerGov | Open311 GeoReport v2 | ✅ | — | ✅ | — | — | — |
| **CivicPlus (SeeClickFix)** | CivicPlus | Public API (SeeClickFix API v2) | ✅ | — | ✅ | ✅ | — | — |
| **Generic Open311** | any GeoReport v2 endpoint | Open standard | ✅ | — | ✅ | — | — | — |
| **Other REST System** | any vendor with a JSON REST API | Generic, self-configured (⚠ not vendor-certified) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Dashes reflect hard limits of the vendor's public interface: the Open311 spec
has no third-party status-update, comment, or attachment endpoints, and
SeeClickFix's public API exposes comments but not document upload or asset
inventories. Everything the vendor's interface allows is wired.

**Purpose-built vs. generic.** Accela, CivicPlus/SeeClickFix, and Tyler (Open311)
are implemented against each platform's actual, documented API and work out of
the box with account credentials or the jurisdiction's GeoReport v2 endpoint.

Everything else — Trimble Cityworks, SDL (Spatial Data Logic), Edmunds
GovTech/MCSJ, GovPilot, FastTrackGov, Polimorphic, and any other vendor that
exposes a JSON REST API — is served by **one** connector, **Other REST System
(Generic Connector)**. It speaks plain JSON-over-HTTPS and takes the base URL,
auth style, endpoint paths, and field names as configuration. This is
deliberately honest: it is a configurable generic client, **not certified
against any specific vendor's API**. Once the vendor hands you a base URL and
key you configure it from their API docs and confirm it with the built-in
connection check before relying on it in production. If your vendor differs from
the common REST defaults (paths, field names, status words), override just those
in the connector's settings.

## Verifying without vendor access

You don't need a paid production tenant to prove the pipeline works — several
vendors offer free developer/test environments that exercise the exact same
push/pull/comment/photo/asset code paths as production:

- **Accela** — free developer account at
  [developer.accela.com](https://developer.accela.com): register an app,
  then use the Test API Token utility and sandbox agency to exercise the real
  Construct API.
- **CivicPlus SeeClickFix** — public API docs at
  [dev.seeclickfix.com](https://dev.seeclickfix.com) with a replicated test
  environment at `test.seeclickfix.com`; personal access tokens come from any
  account's Password & Security page.
- **Open311/Tyler** — many cities run public GeoReport v2 endpoints (list at
  the [Open311 wiki](https://wiki.open311.org/GeoReport_v2/Servers/)) that
  allow read access without a key — enough to verify pull.
- **Other REST System (Cityworks, SDL, Edmunds, GovPilot, FastTrackGov,
  Polimorphic, …)** — served by the single generic connector, which is not
  certified against any specific vendor. Point it at a mock/staging endpoint (or
  the vendor's test tenant) to validate the pipeline, and always run the
  connection check, before relying on it in production.

## Setting up a connection

Setup is a guided three-step wizard designed for non-technical staff — no
API knowledge needed:

1. Open **Admin Console → Setup & Integration → Connect Your Other Town
   Systems** and press **Set up** on the system your town uses.
2. **Before you start** — the wizard lists in plain language exactly what to
   have on hand, and includes a **ready-to-send email** (copy button included)
   asking the vendor for precisely the right access. Close the wizard and come
   back whenever the vendor replies.
3. **Enter the details** — paste each item the vendor sent; every field has a
   plain-language hint and an example. Pick how the systems should work
   together ("Keep both systems in sync" is pre-selected). Rarely-needed
   fields are tucked under *Optional settings*.
4. **Final check** — the wizard tests the connection live. If it works, the
   connection turns on automatically and you're done. If not, it explains the
   problem in plain language ("the password looks wrong", "check the web
   address for typos") with the technical details one click away for the
   vendor's support team. Entries are saved either way, so you can retry
   anytime.

For platforms that also send things *to* Pinpoint (e.g. Polimorphic's AI
intake), the wizard's success screen shows the inbound webhook address with a
copy button and tells you to pass it to the vendor — the request email
template already includes it.

### Inbound webhook payload

`POST /api/integrations/webhook/{platform}/{token}`

```json
{
  "external_id": "CASE-12345",
  "description": "Streetlight out at 4th & Main",
  "service_code": "STREETLIGHT",
  "status": "open",
  "address": "401 Main St",
  "lat": 40.21, "long": -74.01,
  "first_name": "Ada", "email": "ada@example.com",
  "media_urls": ["https://…/photo.jpg"],
  "comments": [
    {"external_id": "cmt-1", "author": "AI Front Desk", "content": "Caller says it flickers at night"}
  ]
}
```

- Unknown/omitted `service_code` falls back to the integration's
  `default_local_service_code` config, then to the first active category.
- Posting the same `external_id` again updates the linked request's status
  and/or appends new comments (`description` is optional on updates).
- Comments are deduplicated by their `external_id`.
- Rate limited to 60/minute; authenticated by the per-integration token.

## Advanced configuration

The `config` JSON on each integration accepts connector-specific keys beyond
what the UI exposes (set them via `PUT /api/integrations/{id}`):

- `share_pii: true` — include reporter name/email/phone in pushes.
- `import_new_records: true` — pull creates new Pinpoint requests for
  platform-originated records (not just status updates on linked ones).
- `service_code_map` — map platform category names to local service codes for
  imported records, e.g. `{"Pothole Repair": "pothole"}`.
- `sync_assets: true` — enable the daily asset inventory sync;
  `assets_on_resident_portal` (default true) and `asset_service_codes` control
  the generated map layer. The layer id is stored back in `asset_layer_id`.
- `status_map_out` / `status_map_in` — override status vocabulary mapping,
  e.g. `{"in_progress": "Under Review"}`.
- Other REST System (the generic connector — Cityworks, SDL, Edmunds, GovPilot,
  FastTrackGov, Polimorphic, etc.):
  `create_path`, `get_path`, `list_path`, `status_path`, `auth_style`
  (`bearer` | `api_key_header` | `basic` | `query`), `auth_header`,
  `id_field`, `status_field`, `updated_field`, `list_items_field`,
  `field_map` (rename outbound fields; map a field to `null` to omit it), and
  `static_fields` (constants merged into every create body). Comments:
  `comments_path`, `comment_id_field`, `comment_text_field`,
  `comment_author_field`, `comment_created_field`. Documents:
  `documents_path`, `document_file_field`. Assets: `assets_path` (accepts a
  GeoJSON FeatureCollection directly, or a JSON list mapped via
  `asset_id_field`/`asset_name_field`/`asset_lat_field`/`asset_long_field`).
- Accela: `environment` (PROD/TEST), `record_type`, `api_base`/`auth_base` overrides.
- Open311/Tyler: `jurisdiction_id`, `default_service_code`.

## Operational notes

- Poll intervals live in `backend/app/core/celery_app.py`:
  `pull-integration-updates` and `pull-integration-comments` (15 min),
  `sync-integration-assets` (daily).
- Tables: `integration_configs`, `integration_links`, `integration_sync_logs`
  (Alembic revision `a1b2c3d4e5f6`; also auto-created on startup).
- Staff can see a request's external links via
  `GET /api/integrations/requests/{service_request_id}/links`.
- Requests that arrive *from* a platform are never echoed back to it
  (loop protection via `source = integration_<platform>`).
