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

  The window is stamped *before* the fetch and re-read with a five-minute
  overlap. Vendor timestamps come from the vendor's clock at edit time and become
  queryable some time after, so an exact boundary drops records that fall just
  before it; replays are harmless because every record is matched to its existing
  link and applied only if something changed. A failed poll leaves the watermark
  where it was, so the next run retries the window it missed rather than stepping
  over it.
- **Asset management** — mirrors the platform's asset inventory (hydrants,
  streetlights, signs…) into a Pinpoint map layer as GeoJSON points, so residents
  can attach reports to the exact asset and staff see asset-linked request
  history. The request's `matched_asset` is included in outbound pushes.

  Two separate things, deliberately: the **Copy their assets to my map** button
  runs the sync once, now, and changes no settings. The nightly Beat job runs
  only for connections whose `sync_assets` setting is on, which is a field in the
  wizard. The button used to switch that setting on as a side effect, enrolling
  the connection in a nightly job from one click with nothing on screen saying so
  and no way back.
- **Inbound webhook** — each connection gets a unique tokenized URL
  (`/api/integrations/webhook/{platform}/{token}`). Platforms POST a
  normalized JSON payload to create requests in Pinpoint or update ones they
  originated. Repeat posts with the same `external_id` become status updates,
  and a `comments` array attaches comments in the same call. A connection whose
  sync direction is **push** refuses inbound records with 403 — the direction the
  admin chose is enforced here, not just on the outbound side.

All sync activity is logged to `integration_sync_logs` and visible per-platform
in the admin UI. Sync failures never block the core request lifecycle.

### Health monitoring

Each connection reports health under `govtech:<platform>` in the same
`connector_health` table as the built-in capabilities, so it inherits the same
escalation, the same daily digest email and the same mute.

Every real call to the vendor writes that row: a resident's report being pushed,
a status update, the 15-minute poll, the comment and asset jobs, an admin
pressing **Check connection**, and the daily sweep, which tests every *enabled*
connection whether or not any resident traffic has touched it. The poll runs
behind the same circuit breaker as a push, so a vendor that has stopped
answering is not called again on our schedule until a cooldown elapses. That last one is what makes a
vendor outage visible on a quiet weekend instead of on Monday from a resident —
and what keeps a healthy connection from ageing into `stale` and emailing the
town that Accela may stop working when nothing is wrong with it.

Disabled connections are never tested. A connection a town switched off has not
made a mistake, and an amber badge on it is the noise that teaches people to
ignore badges.

The cards read that row and nothing else for their status pill, in the same
vocabulary as the provider cards — *Working*, *Not working*, *Not checked yet*,
*Set up · we cannot test this one*. Deliberately not "is it switched on", which
is a fact about our own database that stays true through a revoked key. And
because these rows sit in the same table as everything else, the same **Mute
alerts** button is on the card: it stops the emails for a week and changes
nothing on screen, so a known problem never becomes an invisible one.

### Privacy

- Reporter PII (name, email, phone) is **not** shared with external platforms
  unless the integration's config sets `share_pii: true`.
- Embedded photos are never sent inline in JSON payloads; they are uploaded
  through the platform's document API where one exists, otherwise only
  `http(s)` media URLs are shared.
- Vendor credentials are held in the configured Secret Manager where there is
  one, with only an opaque `@secret:` reference on the row; otherwise they are
  encrypted at rest (Fernet derived from `SECRET_KEY`). Either way they are never
  returned by the API after being saved. The card reports which of the two is
  true, and says so explicitly when only *some* fields made it to the vault.
- Disconnecting a connection deletes its `INTEGRATION_<PLATFORM>_<FIELD>` entries
  from the vault as well as the row, so a credential an admin revokes by pressing
  Disconnect is actually gone rather than left live and unlisted.

## Supported platforms

| Platform | Vendor | Connection type | Push | Status out | Pull | Comments | Photos | Assets |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Accela** | Accela Civic Platform | Public API (Construct API v4, OAuth2) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Esri ArcGIS** | Esri (ArcGIS Online / Enterprise) | Public API (Feature Service REST, API key or token) | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| **Tyler Technologies** | Tyler 311 / MyCivic / EnerGov | Open311 GeoReport v2 | ✅ | — | ✅ | — | — | — |
| **CivicPlus (SeeClickFix)** | CivicPlus | Public API (SeeClickFix API v2) | ✅ | — | ✅ | ✅ | — | — |
| **Generic Open311** | any GeoReport v2 endpoint | Open standard | ✅ | — | ✅ | — | — | — |
| **Other REST System** | any vendor with a JSON REST API | Generic, self-configured (⚠ not vendor-certified) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Dashes reflect hard limits of the vendor's public interface: the Open311 spec
has no third-party status-update, comment, or attachment endpoints, SeeClickFix's
public API exposes comments but not document upload or asset inventories, and a
feature layer is a table of rows with no comment model of its own. Everything the
vendor's interface allows is wired.

**SeeClickFix report forms.** Creating an issue means answering the request
type's report form: the connector fetches `/request_types/{id}`, fills the
questions a resident's report answers (title, description, address, photo
links), and sends the rest as `answers` keyed by each question's `primary_key`.
Required questions Pinpoint cannot answer — "Depth of pothole?", say — are
answered once per connection via the **Extra answers** setting
(`{"142": "SHALLOW"}`); the connection check names any that are still missing
rather than letting each resident's report take a 422. Authenticate with a
Personal Access Token (`Authorization: Bearer`); username/password Basic remains
only as a fallback for older service accounts.

**Purpose-built vs. generic.** Accela, Esri ArcGIS, CivicPlus/SeeClickFix, and
Tyler (Open311) are implemented against each platform's actual, documented API
and work out of the box with account credentials or the jurisdiction's GeoReport
v2 endpoint.

**Why ArcGIS reaches further than it looks.** The ArcGIS connector targets one
feature layer, and Survey123, Field Maps, Experience Builder, and ArcGIS
Dashboards all read and write that same layer — so connecting the layer also
connects whatever intake and field stack the town has built on top of it. Spatial
Data Logic's SDL Portal syncs with ArcGIS Online, which reaches those towns too.
Because a town using Esri maps in Pinpoint already has an org API key on file,
the connector reuses it when the key box is left blank — only for layers hosted
on `*.arcgis.com`, so the org-wide key is never sent to a self-hosted or
misconfigured address (turn reuse off entirely with `reuse_maps_api_key=false`).

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
- **Esri ArcGIS** — a free ArcGIS Developer account includes a hosted feature
  layer and an API key. Publish a point layer with editing and attachments
  enabled, point the connector at its `/FeatureServer/0` URL, and the connection
  check will report the layer name and exactly which of Create/Update/attachments
  are on.
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

### What "the connection works" means

The check hits an endpoint a bad credential actually fails, wherever the platform
has one, and says so plainly where it does not. The result carries `verified`:

| Platform | What the check does | `verified` |
| :--- | :--- | :---: |
| **Accela** | token from the sign-in's refresh token (or the password-grant fallback), then a records probe | ✅ |
| **CivicPlus (SeeClickFix)** | signs in against `/profile` | ✅ with credentials |
| **Other REST System** | calls the list endpoint with your key attached | ✅ with credentials |
| **Open311 / Tyler** | reads `/services.json` | ❌ — see below |

`verified: false` means the server answered but nothing here exercised your
credentials, and the UI says "Reachable — credentials not checked" rather than
"Connected". GeoReport v2 has no authenticated read endpoint at all: the
`api_key` only matters on the POST that files a record, which a connection check
must not do. The generic connector reports it too when no key is saved, because
its request then carries no credential and a vendor allowing anonymous reads
would answer 200 regardless. In both cases the credentials are first exercised on
the first real push, so send yourself a test report to confirm.

Pressing **Check connection** also clears the circuit breaker for that connection.
Somebody who has just fixed a credential should not wait out a cooldown the
broken one earned, so the next queued report is attempted immediately.

For platforms that also send things *to* Pinpoint (e.g. Polimorphic's AI
intake), the wizard's success screen shows the inbound webhook address with a
copy button and tells you to pass it to the vendor — the request email
template already includes it.

### Accela: signing in instead of storing a password

Accela is connected through OAuth2 **authorization code** sign-in
([Accela docs](https://developer.accela.com/docs/construct-authCodeFlow.html)),
not by handing us an agency password. The wizard asks only for the agency name,
environment, and record type; pressing **Sign in with Accela** sends the admin
to Accela's own login and consent page. Pinpoint stores only the refresh token
that comes back, in the same credential vault as every other secret — and any
password left over from a previous setup is deleted at that moment.

The developer-portal app belongs to Pinpoint, not to each town, so its
credentials are **deployment-level** rather than something a clerk types in.
Set them as environment variables, or as Secret Manager entries of the same
name:

| Key | Required | What it is |
| --- | --- | --- |
| `ACCELA_CLIENT_ID` | yes | App ID from developer.accela.com |
| `ACCELA_CLIENT_SECRET` | yes | Its matching secret |
| `ACCELA_REDIRECT_URI` | no | Pin the callback URL when the registered one differs from the town's own domain (shared-host deployments, or a proxy that rewrites the host) |

Without them the wizard says so plainly and falls back to the username/password
option. The exact callback URL to register on the app is returned by
`GET /api/integrations/accela/oauth/status`. It resolves in this order:
`ACCELA_REDIRECT_URI` if set; otherwise the deployment's configured public
origin (the township's custom domain, else the `DOMAIN` environment variable)
plus `/api/integrations/accela/oauth/callback`; and only as a logged last
resort the address on the request itself — which, behind the TLS-terminating
proxy, is `http://` and will not match what Accela has registered, so make
sure one of the first two is set.

Two details worth knowing when reading the code:

- **Tokens rotate.** Accela retires the old refresh token on every exchange, so
  the connector writes the new one straight back through the vault
  (`build_connector_for` attaches the writer). Access tokens are cached per
  agency for their advertised lifetime, which also stops two concurrent syncs
  from rotating each other out.
- **The callback is deliberately unauthenticated.** It arrives as a browser
  redirect with no session, so an HMAC-signed, ten-minute `state` bound to one
  integration and one admin is what authorizes it. Without that check, an
  attacker could feed an admin their own authorization code and point the
  town's Accela sync at their account.

The password grant still works for towns whose Accela administrator prefers a
service account — it lives behind *"Use an Accela username and password
instead"* in the wizard and needs the town's own Client ID and Secret.

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
- Rate limited to 60/minute **per connection**, not per source address: one
  vendor's egress IP serves every town on their platform, so a per-IP bucket let
  a busy neighbour exhaust yours.
- Authenticated by the per-integration token, compared with a constant-time
  check.
- A connection whose sync direction is `push` answers 403 — it is configured to
  send only.

**Rotating the address.** The token is in the URL path, which is where a URL's
secrets are least well kept: reverse-proxy access logs, the vendor's own outbound
logs, and any screenshot of the setup page. **Issue a new address** on the
connection's card (`POST /api/integrations/{id}/regenerate-webhook-token`)
replaces it. The old address stops working immediately, so send the vendor the
new one — until you do, their posts are refused.

## Advanced configuration

The `config` JSON on each integration accepts connector-specific keys beyond
what the UI exposes (set them via `PUT /api/integrations/{id}`):

- `share_pii: true` — include reporter name/email/phone in pushes.
- `import_new_records: true` — pull creates new Pinpoint requests for
  platform-originated records (not just status updates on linked ones).
- `service_code_map` — map platform category names to local service codes for
  imported records, e.g. `{"Pothole Repair": "pothole"}`.
- `sync_assets: true` — enable the **nightly** asset inventory sync. It is a
  field in the wizard, and the one-off *Copy their assets to my map* button does
  not set it. `assets_on_resident_portal` (default true) and `asset_service_codes`
  control the generated map layer; the layer id is stored back in
  `asset_layer_id`.
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
- Accela: `environment` (PROD/TEST), `record_type`, `scope` (default
  `records assets`), `api_base`/`auth_base` overrides. In the sign-in flow an
  `auth_base` override must be a public URL on an accela.com host — the code
  exchange posts the deployment-level client secret there, so anything else
  is refused. `auth_mode` is set to `authorization_code` by the sign-in
  callback and is informational.
- Esri ArcGIS: `layer_url` (required — the layer, ending `/FeatureServer/0`),
  `portal_url` (Enterprise only; default `https://www.arcgis.com`), `field_map`
  (Pinpoint field → layer column; defaults follow Esri's citizen-request
  template — `reqid`, `reqcategory`, `details`, `address`, `status`, `submitdt`),
  `static_fields`, `wkid` (default 4326), `object_id_field`,
  `external_id_field`, `edit_date_field` (detected from the layer's editor
  tracking when blank), `status_notes_field`, `page_size`/`max_pull_pages`,
  `reuse_maps_api_key`, and for assets `asset_layer_url` plus
  `asset_id_field`/`asset_name_field`/`asset_type_field`. Attributes the layer
  doesn't have are dropped with a warning rather than failing the whole edit,
  and date columns are converted to the epoch milliseconds ArcGIS expects.
- Open311/Tyler: `jurisdiction_id`, `default_service_code`.

Keys are validated against the platform's declared fields, so a typo is refused
rather than silently stored as a setting nothing will ever read — and a
credential key cannot name an arbitrary `INTEGRATION_*` entry in your vault.

**Clearing a setting.** Sending a key with a value of `null` deletes it. An empty
string still means "leave it as it is", which is what the wizard sends for fields
you did not touch; the *Clear this setting* control beside a saved field is what
sends the null.

**What the generic connector claims.** Its optional capabilities follow the paths
you configure: `comments` only with `comments_path`, `documents` only with
`documents_path`, `assets` only with `assets_path`, and `work_orders` only once
at least one work-order field is mapped. Leave a path blank and Pinpoint will not
poll it. It used to claim all of them unconditionally, which meant the 15-minute
comment poll wrote a 404 to `integration_sync_logs` for an endpoint the vendor
never had — so a connection that was working perfectly showed as failing.

## Operational notes

- Poll intervals live in `backend/app/core/celery_app.py`:
  `pull-integration-updates` and `pull-integration-comments` (15 min),
  `sync-integration-assets` (daily), `daily-connector-check` (daily).
- Each of those tasks takes an optional `integration_id`. The Beat schedule omits
  it and covers everything; the card buttons pass it, so **Check for updates**
  polls the connection you clicked and not every vendor the town uses. The
  endpoint enqueues both the update and comment jobs and reports which started —
  a partial start says so rather than claiming nothing happened.
- Tables: `integration_configs`, `integration_links`, `integration_sync_logs`
  (Alembic revision `a1b2c3d4e5f6`; also auto-created on startup).
  `integration_configs.platform` is uniquely indexed (`7d73fe63d6e3`) — one
  connection per platform, so a concurrent double-create cannot make every report
  push twice. That revision also adds `integration_links.documents_pushed_count`,
  which the models had and the migration chain did not, so document pushes raised
  `UndefinedColumn` on Alembic-only deployments.
- Revision `a7029676a2bc` drops the unused `integration_links.documents_pushed`
  boolean. It is a `drop_column`, so the startup migration gate holds the
  container until `PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION=1` is set — deliberately a
  separate revision, so the correctness fix above applies unattended and only the
  tidy-up waits for a human.
- Staff can see a request's external links via
  `GET /api/integrations/requests/{service_request_id}/links`; the external record
  ids and their status are shown on the request in the staff dashboard.
- Requests that arrive *from* a platform are never echoed back to it
  (loop protection via `source = integration_<platform>`).
