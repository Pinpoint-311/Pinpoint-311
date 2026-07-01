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
  `integration_link`.
- **Push status** — when staff change a request's status, the change is
  mirrored to every linked platform record.
- **Pull** — a Celery Beat job polls each pull-enabled platform every 15
  minutes; external status changes are applied to the linked local request and
  recorded in the request's audit log (actor type `integration`).
- **Inbound webhook** — each connection gets a unique tokenized URL
  (`/api/integrations/webhook/{platform}/{token}`). Platforms POST a
  normalized JSON payload to create requests in Pinpoint or update ones they
  originated. Repeat posts with the same `external_id` become status updates.

All sync activity is logged to `integration_sync_logs` and visible per-platform
in the admin UI. Sync failures never block the core request lifecycle.

### Privacy

- Reporter PII (name, email, phone) is **not** shared with external platforms
  unless the integration's config sets `share_pii: true`.
- Base64-embedded photos are never pushed — only `http(s)` media URLs.
- Vendor credentials are encrypted at rest (Fernet derived from `SECRET_KEY`)
  and are never returned by the API after being saved.

## Supported platforms

| Platform | Vendor | Connection type | Push | Status out | Pull |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Accela** | Accela Civic Platform | Public API (Construct API v4, OAuth2) | ✅ | ✅ | ✅ |
| **Tyler Technologies** | Tyler 311 / MyCivic / EnerGov | Open311 GeoReport v2 | ✅ | — | ✅ |
| **CivicPlus (SeeClickFix)** | CivicPlus | Public API (SeeClickFix API v2) | ✅ | — | ✅ |
| **SDL** | Spatial Data Logic | Vendor-issued REST API | ✅ | ✅ | ✅ |
| **Edmunds GovTech** | Edmunds (MCSJ) | Vendor-issued REST API | ✅ | ✅ | ✅ |
| **GovPilot** | GovPilot | Vendor-issued REST API | ✅ | ✅ | ✅ |
| **FastTrackGov** | Harris / MS Govern | Vendor-issued REST API | ✅ | ✅ | ✅ |
| **Polimorphic** | Polimorphic | Bidirectional webhooks + workspace API | ✅ | ✅ | ✅ |
| **Generic Open311** | any GeoReport v2 endpoint | Open standard | ✅ | — | ✅ |

**A note on "vendor-issued REST API" platforms.** SDL, Edmunds, GovPilot,
FastTrackGov, and Polimorphic do not publish one universal public API — they
provision REST endpoints and credentials per customer through their support or
implementation teams. Pinpoint's connectors for these platforms bake in each
vendor's conventional auth style and expose the endpoint paths, field names,
and status vocabulary as configuration, so once the vendor hands you a base URL
and key the connection works without code changes. Accela and SeeClickFix have
fully public, documented APIs and work out of the box with account credentials;
Tyler (and anything else speaking Open311) works against the jurisdiction's
GeoReport v2 endpoint.

## Setting up a connection

1. Open **Admin Console → Setup & Integration → GovTech Platform Connections**.
2. Click **Connect** on a platform card, fill in the credentials/config fields
   (each card links to the vendor's docs and states what to request from the
   vendor), and **Save & Connect**.
3. Click **Test Connection** — this performs a live authenticated call.
4. Flip the toggle to enable, and choose a sync direction:
   - *Push only* — Pinpoint is the intake front door; the platform is the system of record.
   - *Pull only* — the platform originates work; Pinpoint mirrors it.
   - *Bidirectional* — full two-way sync.
5. For platforms that push into Pinpoint (e.g. Polimorphic's AI intake), copy
   the **Inbound Webhook URL** from the card and give it to the vendor.

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
  "media_urls": ["https://…/photo.jpg"]
}
```

- Unknown/omitted `service_code` falls back to the integration's
  `default_local_service_code` config, then to the first active category.
- Posting the same `external_id` again updates the linked request's status.
- Rate limited to 60/minute; authenticated by the per-integration token.

## Advanced configuration

The `config` JSON on each integration accepts connector-specific keys beyond
what the UI exposes (set them via `PUT /api/integrations/{id}`):

- `share_pii: true` — include reporter name/email/phone in pushes.
- `status_map_out` / `status_map_in` — override status vocabulary mapping,
  e.g. `{"in_progress": "Under Review"}`.
- Generic REST connectors (SDL, Edmunds, GovPilot, FastTrackGov, Polimorphic):
  `create_path`, `get_path`, `list_path`, `status_path`, `auth_style`
  (`bearer` | `api_key_header` | `basic` | `query`), `auth_header`,
  `id_field`, `status_field`, `updated_field`, `list_items_field`,
  `field_map` (rename outbound fields; map a field to `null` to omit it), and
  `static_fields` (constants merged into every create body).
- Accela: `environment` (PROD/TEST), `record_type`, `api_base`/`auth_base` overrides.
- Open311/Tyler: `jurisdiction_id`, `default_service_code`.

## Operational notes

- Poll interval lives in `backend/app/core/celery_app.py`
  (`pull-integration-updates`, default 15 min).
- Tables: `integration_configs`, `integration_links`, `integration_sync_logs`
  (Alembic revision `a1b2c3d4e5f6`; also auto-created on startup).
- Staff can see a request's external links via
  `GET /api/integrations/requests/{service_request_id}/links`.
- Requests that arrive *from* a platform are never echoed back to it
  (loop protection via `source = integration_<platform>`).
