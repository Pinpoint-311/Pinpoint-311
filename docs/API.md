# Pinpoint 311 API Reference

All routes are served under `https://<your-domain>/api`. Requests and responses
are JSON unless noted otherwise.

The route tables in this document were **generated from the running
application's route list** (`app.main:app`), not written by hand. The access
column comes from `app/core/route_access.py`, which reads each route's real
dependency chain. The same module labels every operation in the OpenAPI schema
(`x-pinpoint-access`). `backend/tests/test_route_access.py` fails if a route
becomes public without being added to the reviewed list. To regenerate the
tables after changing routes, walk `app.routes` with `route_access()`; the
October 2026 review used exactly that script.

- [Interactive docs and the OpenAPI schema](#interactive-docs-and-the-openapi-schema)
- [Authentication and roles](#authentication-and-roles)
- [Open311 GeoReport v2](#open311-georeport-v2)
- [Rate limits](#rate-limits)
- [Errors](#errors)
- [Route groups and required role](#route-groups-and-required-role)
- [Every route](#every-route)

---

## Interactive docs and the OpenAPI schema

`/api/docs` (Swagger UI), `/api/redoc` and `/api/openapi.json` are served
**only when `DEBUG=true`**. In production all three return `404`, because a
full route and model map helps attackers more than it helps anyone else. To
browse the schema, run a local or development instance with `DEBUG=true`. Each
operation's description starts with an **Access:** line that states who may
call it.

---

## Authentication and roles

### Tokens

Authenticated routes take a bearer JWT:

```
Authorization: Bearer <token>
```

Tokens are HS256 JWTs signed with the deployment's `SECRET_KEY` and valid for
8 hours (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 480). The API refuses
single-purpose tokens, such as onboarding links. A deactivated account gets
`403` even while its token is still valid.

Logging out (`GET /api/auth/logout`) does **not** revoke the JWT. It stays valid
until it expires. Clients should discard it.

### Getting a token

| Flow | How |
|---|---|
| **SSO (normal)** | 1. `GET /api/auth/login?redirect_uri=<frontend callback>` returns `{"auth_url", "state"}`.<br>2. Send the browser to `auth_url`. The identity provider (Auth0, Entra ID, Google, Okta or generic OIDC) redirects back to `/api/auth/callback`.<br>3. The callback redirects to `redirect_uri?token=<jwt>`.<br>4. Accounts are matched by email. The account must already exist (an admin creates it), and the provider must not report the email as unverified. |
| **First-run bootstrap** | Works only until an identity provider is configured. `POST /api/auth/bootstrap` (form field `password` = `INITIAL_ADMIN_PASSWORD`, 5/minute) issues a one-time link. `GET /api/auth/bootstrap/{token}` exchanges it for an admin session. |
| **Onboarding link** (managed hosting) | `POST /api/auth/onboarding/redeem` with a single-use signed token minted by the provisioning API. |
| **Break-glass** (managed hosting) | `POST /api/provisioning/break-glass` with a panel-signed token. Returns a time-boxed admin JWT for a visible `state-ops:` account. Every use is audited. |

There is no username/password login and no credential-free demo login.

`GET /api/auth/me` returns the signed-in account.

### Access classes

| Class | Who | Notes |
|---|---|---|
| `public` | Anyone | Resident intake, Open311 reads, public settings, health, sign-in flows. Some of these verify a token inside the handler; see the access note on the route. |
| `signed-in` | Any active account | `GET /api/auth/me`, `GET /api/auth/logout`, `DELETE` of your own comment (admins can delete any). |
| `staff` | `staff` or `admin` | **Department-scoped.** Any route that reads or changes a single request uses `app/api/scoping.scoped_request`. A non-admin sees:<ul><li>requests routed to their departments</li><li>requests assigned to them by name</li><li>unrouted requests</li></ul>Anything else returns `404`, not `403`, so the request's existence is not disclosed. |
| `researcher` | `researcher` or `admin` | The Research Suite module must be enabled. Exports are de-identified, and locations are fuzzed unless an **admin** asks for `privacy_mode=exact`. |
| `admin` | `admin` | Users, services, departments, providers and secrets, audit, backups, retention, integrations, setup. The last active admin cannot be demoted or deactivated. |
| `orchestrator-token` | Managed-hosting panel | `X-Provisioning-Token` / `X-Panel-Token` header compared in constant time to `PROVISIONING_TOKEN`. These routes return `404` when no token is set. |

Every successful authenticated write is recorded in the admin audit log by
middleware (`AdminActionAuditMiddleware`).

---

## Open311 GeoReport v2

**Base URL:** `https://<your-domain>/api/open311/v2`
**Spec:** <http://wiki.open311.org/GeoReport_v2>
**Format:** JSON only (no `.xml` routes). `jurisdiction_id` is not used: each
deployment is a single jurisdiction.

### API keys

**No API key is required, and none is checked.** Anyone can call
`POST requests.json`, as the town's resident portal does. Abuse is controlled
by:

- a per-client limit of 10/minute (keyed on the real client address resolved
  from the trusted proxy chain; `X-Forwarded-For` cannot be spoofed)
- content moderation
- photo redaction
- request body size limits

`discovery.json`'s `key_service` field says this. If you are building an
integration that needs a higher volume, contact the town.

### Discovery

```
GET /api/open311/v2/discovery.json
```

```json
{
  "changeset": "2026-03-31T00:00:00Z",
  "contact": "You may email support@pinpoint311.org for any questions or issues.",
  "key_service": "No API key is required. POST requests.json is open to anonymous callers and rate limited per client address (10/minute).",
  "type": "production",
  "endpoints": [{
    "specification": "http://wiki.open311.org/GeoReport_v2",
    "url": "https://<your-domain>/api/open311/v2",
    "changeset": "2026-03-31T00:00:00Z",
    "type": "production",
    "formats": ["application/json"]
  }],
  "extensions": { "public_portal": { "...": "..." } }
}
```

### Service list and definition

```
GET /api/open311/v2/services.json
GET /api/open311/v2/services/{service_code}.json
```

```json
[{
  "service_code": "POTHOLE",
  "service_name": "Pothole",
  "description": "Report potholes on roads or parking lots",
  "metadata": true,
  "type": "realtime",
  "keywords": "pothole",
  "group": "municipal"
}]
```

The definition adds `attributes`, which lists the request fields (`description`,
`address`, `lat`, `long`, `email`, `first_name`, and so on) with `datatype`,
`required` and `order`.

- Every active category is listed, including categories whose reports are
  kept off the public map. Residents can still file those.
- An unknown code returns `404 {"detail": "Service not found: <code>"}`.
- A category's location rule (`required` / `optional` / `none`) is reflected in
  whether `address`, `lat` and `long` are listed and required.

### Submit a request

```
POST /api/open311/v2/requests.json
Content-Type: application/json
```

```json
{
  "service_code": "POTHOLE",
  "description": "Large pothole in the eastbound lane near Oak Ave.",
  "address": "123 Main St",
  "lat": 40.2171,
  "long": -74.7429,
  "email": "resident@example.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "phone": "555-0100",
  "media_urls": ["data:image/jpeg;base64,..."],
  "preferred_language": "en"
}
```

| Field | Required | Notes |
|---|---|---|
| `service_code` | yes | An active service code. Unknown code returns `400`. |
| `description` | yes | At least 10 characters. Moderated. |
| `email` | yes | A valid address, used for status notifications. |
| `address` | depends on category | Up to 500 characters. |
| `lat`, `long` | depends on category | −90..90 and −180..180. |
| `first_name`, `last_name`, `phone` | no | Encrypted at rest. Never returned by public endpoints. |
| `media_urls` | no | Up to 3 photos. Faces and plates are redacted, and a photo that cannot be cleared is held for staff review. |
| `custom_fields` | no | Answers to the category's custom questions. |
| `is_public` | no | `false` asks for the report to be unlisted. Honored only when the town enables unlisted reports. |

The response is `201 Created` and contains only the acknowledgement fields.
No staff fields, assignee or priority are included.

```json
{
  "service_request_id": "REQ-20261018-66EA36DA",
  "service_code": "POTHOLE",
  "service_name": "Pothole",
  "description": "Large pothole in the eastbound lane near Oak Ave.",
  "status": "open",
  "address": "123 Main St",
  "lat": 40.2171,
  "long": -74.7429,
  "requested_datetime": "2026-10-18T05:01:52.340482Z",
  "photos_pending_review": 0
}
```

`service_request_id` is also the tracking token.

Example with curl:

```bash
curl -sS -X POST https://<your-domain>/api/open311/v2/requests.json \
  -H 'Content-Type: application/json' \
  -d '{"service_code":"POTHOLE","description":"Pothole by the school crossing","lat":40.2171,"long":-74.7429,"email":"resident@example.com"}'
```

### Read requests (public)

The spec's `GET requests.json` and `GET requests/{id}.json` **require a staff
JWT** in this implementation, because they return reporter contact details and
staff fields. They are department-scoped. Third-party clients should use the
public equivalents, which never return PII:

```
GET /api/open311/v2/public/requests?status=open,closed&service_code=POTHOLE&limit=100&offset=0
GET /api/open311/v2/public/requests/{service_request_id}
GET /api/open311/v2/tokens/{service_request_id}.json
GET /api/open311/v2/public/requests/{service_request_id}/comments
GET /api/open311/v2/public/requests/{service_request_id}/audit-log
```

```json
[{
  "service_request_id": "REQ-20261018-06013F4D",
  "service_code": "POTHOLE",
  "service_name": "Pothole",
  "description": "Big pothole on Main St",
  "status": "open",
  "address": "1 Main St",
  "lat": 40.0,
  "long": -74.0,
  "requested_datetime": "2026-10-18T05:01:49.169182+00:00",
  "updated_datetime": "2026-10-18T05:09:25.235620+00:00",
  "closed_substatus": null,
  "media_urls": [],
  "photo_count": 1,
  "completion_message": null,
  "completion_photo_url": null,
  "has_completion_photo": false
}]
```

- `status` takes `open`, `in_progress` and `closed`, comma-separated. An
  unknown value returns `400`. (`in_progress` is an extension; spec clients
  should treat it as open.)
- The list leaves out unlisted reports, archived reports, reports in hidden
  categories, and deleted reports. It has no default limit.
- By id (detail, token, comments, audit log), unlisted and hidden-category
  reports are still served. The id is the resident's tracking link. Deleted
  reports return `404`.
- Public responses never include:
  - reporter name, email or phone
  - staff notes or internal comments
  - AI analysis, priority or moderation flags
  - assignee
  - photos still held for review (only a count is shown)
- In the public audit log, staff actors appear as `"Staff"`, and `extra_data`
  holds only a closed report's `substatus` and `completion_message`.
- `POST /public/requests/{id}/comments` (`{"content": "..."}`, 1 to 1000
  characters, 5/minute) adds a moderated comment as "Resident".

### Differences from GeoReport v2

| Area | Spec | Pinpoint 311 |
|---|---|---|
| API key | `api_key` required on POST | Not required and not checked. Rate limited per client instead. |
| POST body | `application/x-www-form-urlencoded`, `attribute[code]=` | JSON body. Fields are top-level (`address`, `media_urls[]`, `custom_fields`). `address_string`, `address_id`, `media_url`, `zipcode`, `device_id` and `account_id` are ignored. |
| POST `email` | optional | required |
| POST response | array `[{service_request_id, token, service_notice, account_id}]` | single object (see above) |
| `GET requests.json` | public, with `start_date`, `end_date`, `status`, `service_request_id` | Staff-only. The public list is `/public/requests`, which has no date filter. |
| `requests/{id}.json`, `tokens/{id}.json` | arrays | Single objects. The token is the `service_request_id`. |
| status values | `open`, `closed` | adds `in_progress` |
| Fields not returned | `status_notes`, `agency_responsible`, `service_notice`, `expected_datetime`, `address_id`, `zipcode`, `media_url` | Only `tokens/{id}.json` returns `status_notes`. The public detail returns `assigned_department_name`. |
| Formats | `.json` and `.xml` | `.json` only |
| `jurisdiction_id` | accepted | not used |
| Errors | `[{"code": 404, "description": "..."}]` | `{"detail": "..."}` (see [Errors](#errors)) |

---

## Rate limits

Limits are per client address. Behind the reverse proxy, the client address
is resolved from the trusted end of `X-Forwarded-For` (`app/core/client_ip.py`),
so a client cannot mint new buckets by forging the header. Exceeding a limit
returns `429`.

| Route | Limit |
|---|---|
| Every route without an explicit limit | `RATE_LIMIT_DEFAULT`, default **500/minute** |
| `POST /open311/v2/requests.json` | 10/minute |
| `POST /open311/v2/public/requests/{id}/comments` | 5/minute |
| `POST /open311/v2/photos/screen` | 12/minute per client, plus 240/minute across the whole deployment |
| `GET /gis/geocode`, `GET /gis/reverse-geocode` | 30/minute per client, plus 600/minute across the whole deployment |
| `POST /system/translate/batch` | 60/minute, max 200 strings / 20,000 characters per call |
| `POST /auth/bootstrap`, `POST /auth/bootstrap/verify` | 5/minute, with lockout |
| `POST /feedback/platform` | 30/minute, plus a daily cap |
| `POST /integrations/webhook/{platform}/{token}` | 60/minute |
| `GET /integrations/accela/oauth/callback` | 20/minute |
| `POST /system/analytics-chat` (staff) | 20/minute |
| `GET /resident-history/requests/{id}` / `POST /resident-history/search` (staff) | 60 / 20 per minute |
| Integration test/sync/lookups/OAuth start (admin) | 6–10/minute |
| Provider test, AI model refresh (admin) | 10 / 6 per minute |

Request bodies are size-capped before routing (`BodySizeLimitMiddleware`) and
again at the proxy.

---

## Errors

```json
{ "detail": "Human-readable message" }
```

Validation errors (`422`) list `loc`, `msg` and `type` for each field. They do
not echo the submitted value back.

| Code | Meaning |
|---|---|
| 400 | Invalid input, for example an unknown status filter or service code |
| 401 | Missing, invalid or expired token |
| 403 | Signed in, but the role is not allowed (or the account is inactive) |
| 404 | Not found, **or** outside your department scope, or the module is disabled |
| 413 | Body too large |
| 422 | Schema validation failed |
| 429 | Rate limited |

---

## Route groups and required role

Counts are per method and path, generated from `app.main:app` (221 routes in
the schema). The columns are the access classes described above.

| Group | Routes | public | orchestrator-token | signed-in | staff | researcher | admin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Authentication | 10 | 8 |  | 2 |  |  |  |
| Users | 9 |  |  |  | 3 |  | 6 |
| Departments | 5 |  |  |  | 2 |  | 3 |
| Services | 9 | 2 |  |  | 1 |  | 6 |
| System | 66 | 7 |  |  | 6 |  | 53 |
| Open311 | 23 | 11 |  |  | 12 |  |  |
| GIS | 13 | 7 |  |  |  |  | 6 |
| Roads | 8 | 1 |  |  | 4 |  | 3 |
| Map Layers | 6 | 2 |  |  |  |  | 4 |
| Comments | 3 |  |  | 1 | 2 |  |  |
| Research Suite | 10 |  |  |  |  | 9 | 1 |
| Health Check | 9 | 4 |  |  |  |  | 5 |
| Audit Logs | 5 |  |  |  |  |  | 5 |
| Setup | 7 |  |  |  |  |  | 7 |
| Provisioning (orchestrator) | 5 | 1 | 4 |  |  |  |  |
| Telemetry (orchestrator) | 1 |  | 1 |  |  |  |  |
| API Usage | 4 |  |  |  | 4 |  |  |
| Data Export | 2 |  |  |  | 1 |  | 1 |
| GovTech Integrations | 21 | 1 |  |  | 3 |  | 17 |
| Platform Feedback | 2 | 1 |  |  | 1 |  |  |
| Resident History | 2 |  |  |  | 2 |  |  |
| Deployment Templates | 1 | 1 |  |  |  |  |  |

---

## Every route

The first line of each handler's docstring. The access column uses the classes above.
| **Total** | **221** | **46** | **5** | **3** | **41** | **9** | **117** |




#### API Usage

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/system/api-usage/cost-estimate` | staff | Get estimated costs based on API usage. |
| GET | `/api/system/api-usage/daily` | staff | Get daily usage breakdown for charting. |
| GET | `/api/system/api-usage/pricing` | staff | Get current pricing information for all tracked services. |
| GET | `/api/system/api-usage/usage` | staff | Get API usage statistics for the specified time period. |

#### Audit Logs

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/audit/anchors` | admin | Recent append-only anchors of the request-audit hash-chain head, plus |
| GET | `/api/audit/export` | admin | Export audit logs to CSV. |
| GET | `/api/audit/logs` | admin | Query audit logs with filtering and pagination. |
| GET | `/api/audit/stats` | admin | Get audit log statistics. |
| GET | `/api/audit/verify-integrity` | admin | Verify the integrity of the audit log chain. |

#### Authentication

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/auth/bootstrap` | public | Generate a one-time magic link for admin access. |
| GET | `/api/auth/bootstrap/auto` | public | Browser-based first-run bootstrap. Renders a password prompt (the |
| POST | `/api/auth/bootstrap/verify` | public | Validate the setup password and mint the initial admin session. |
| GET | `/api/auth/bootstrap/{token}` | public | Use a bootstrap token to get a JWT for admin access. |
| GET | `/api/auth/callback` | public | Auth0 callback endpoint. |
| GET | `/api/auth/login` | public | Initiate Auth0 login flow. |
| GET | `/api/auth/logout` | signed-in | Logout endpoint - logs the logout event and returns Auth0 logout URL. |
| GET | `/api/auth/me` | signed-in | Get current authenticated user with departments |
| POST | `/api/auth/onboarding/redeem` | public | Exchange a one-time onboarding link (minted by the provisioning API) |
| GET | `/api/auth/status` | public | Get authentication configuration status. |

#### Comments

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/requests/{request_id}/comments` | staff | Get all comments for a service request (staff/admin, own departments). |
| POST | `/api/requests/{request_id}/comments` | staff | Add a comment to a service request (staff/admin, own departments) |
| DELETE | `/api/requests/{request_id}/comments/{comment_id}` | signed-in | Delete a comment (only owner or admin can delete) |

#### Data Export

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/export/requests` | admin | Export 311 requests as CSV, JSON, or GeoJSON. |
| GET | `/api/export/statistics` | staff | Export aggregated statistics as CSV or JSON. |

#### Departments

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/departments/` | staff | List all departments (staff only — routing_email is internal) |
| POST | `/api/departments/` | admin | Create a new department (admin only) |
| DELETE | `/api/departments/{dept_id}` | admin | Delete department (admin only) |
| GET | `/api/departments/{dept_id}` | staff | Get department by ID (staff only) |
| PUT | `/api/departments/{dept_id}` | admin | Edit a department's name, description or routing email (admin only). |

#### Deployment Templates

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/deploy-templates/{cloud}/{filename}` | public | Serve one deployment template to whoever asks, including a cloud provider. |

#### GIS

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/gis/boundaries` | public | List all configured boundaries |
| POST | `/api/gis/boundaries` | admin | Upload a GeoJSON boundary file (admin only) |
| POST | `/api/gis/boundaries/save-census` | admin | Save a Census boundary as the township boundary |
| GET | `/api/gis/boundaries/{name}` | public | Get a specific boundary with full geometry |
| GET | `/api/gis/census-boundary-search` | admin | Search for a township/city/county boundary from Census TIGERweb API |
| GET | `/api/gis/check-boundary` | public | Check if a point is within a boundary |
| GET | `/api/gis/config` | public | Get maps configuration for the browser. |
| GET | `/api/gis/geocode` | public | Geocode an address to coordinates, using the town's own geocoder. |
| GET | `/api/gis/osm/boundary/{osm_id}` | admin | Fetch GeoJSON boundary from polygons.openstreetmap.fr for an OSM relation |
| GET | `/api/gis/osm/search` | admin | Search for a township/city boundary using OpenStreetMap Nominatim |
| GET | `/api/gis/providers` | public | Map providers a town can choose, for the admin console. |
| GET | `/api/gis/reverse-geocode` | public | Convert coordinates to address, using the town's own geocoder. |
| POST | `/api/gis/township-boundary` | admin | Save the township boundary GeoJSON to system settings |

#### GovTech Integrations

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/integrations` | admin | List configured GovTech integrations, secrets masked (admin only). |
| POST | `/api/integrations` | admin | Create an integration for a platform in the catalog (admin only). |
| POST | `/api/integrations/accela/oauth/start` | admin | Begin the Accela authorization-code flow: returns the URL to send the |
| GET | `/api/integrations/accela/oauth/status` | admin | Whether this deployment can offer Accela sign-in, and the exact callback |
| GET | `/api/integrations/catalog` | staff | List all supported govtech platforms and the fields each requires. |
| POST | `/api/integrations/requests/{request_id}/refresh` | staff | Pull the latest work-order state (assignment, schedule, status, |
| GET | `/api/integrations/requests/{service_request_id}/links` | staff | External platform records linked to a service request (staff, own departments). |
| POST | `/api/integrations/webhook/{platform}/{token}` | public | Inbound intake from a connected platform. |
| DELETE | `/api/integrations/{integration_id}` | admin | Delete an integration and its links and logs (admin only). |
| PUT | `/api/integrations/{integration_id}` | admin | Update an integration's settings or credentials (admin only). |
| GET | `/api/integrations/{integration_id}/backlog` | admin | Reports and updates that have not reached this vendor yet. |
| POST | `/api/integrations/{integration_id}/backlog/{item_id}/discard` | admin | Decide this one should not be sent after all. |
| POST | `/api/integrations/{integration_id}/backlog/{item_id}/retry` | admin | Try this one again now, rather than waiting out its backoff. |
| GET | `/api/integrations/{integration_id}/logs` | admin | Recent sync log entries for one integration (admin only). |
| POST | `/api/integrations/{integration_id}/lookups/refresh` | admin | Pull this vendor's own code lists down and keep them. |
| POST | `/api/integrations/{integration_id}/mapping` | admin | Store a mapping somebody has actually looked at. |
| POST | `/api/integrations/{integration_id}/regenerate-webhook-token` | admin | Issue a new inbound webhook token, invalidating the old one. |
| POST | `/api/integrations/{integration_id}/sync` | admin | Queue an immediate sync with the vendor (admin only, 10/minute). |
| POST | `/api/integrations/{integration_id}/sync-assets` | admin | Run the asset inventory sync immediately (also runs daily via Beat). |
| GET | `/api/integrations/{integration_id}/sync-problems` | admin | Requests whose last sync to this vendor failed, and recent warnings. |
| POST | `/api/integrations/{integration_id}/test` | admin | Test the connection to the vendor API (admin only, 10/minute). |

#### Health Check

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/` | public | API name and pointers to the health check (public). |
| GET | `/api/health` | public | Liveness probe (public). Always `{"status": "healthy"}` while the process serves. |
| GET | `/api/health/` | admin | Comprehensive health check of all system integrations. |
| GET | `/api/health/proactive` | admin | Leading-indicator health for admins: per-check status, values, and the |
| GET | `/api/health/quick` | public | Quick health check for monitoring (no auth required). |
| POST | `/api/health/uptime/check-now` | admin | Manually trigger an uptime check for all services and record results. |
| GET | `/api/health/uptime/history` | admin | Get uptime history for all services over the specified time period. |
| GET | `/api/health/uptime/stats` | admin | Get aggregated uptime statistics (24h, 7d, 30d percentages). |
| GET | `/api/health/version` | public | Build + schema version stamp for the orchestrator/control plane. |

#### Map Layers

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/map-layers/` | public | List all active layers visible on resident portal (public) |
| POST | `/api/map-layers/` | admin | Create a new map layer (admin only) |
| GET | `/api/map-layers/all` | admin | List all layers including inactive (admin only) |
| DELETE | `/api/map-layers/{layer_id}` | admin | Delete a map layer (admin only) |
| GET | `/api/map-layers/{layer_id}` | public | Get a layer by ID. |
| PUT | `/api/map-layers/{layer_id}` | admin | Update a map layer (admin only) |

#### Open311

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/open311/v2/discovery.json` | public | Open311 v2 Discovery endpoint — API metadata and capability advertisement. |
| POST | `/api/open311/v2/photos/screen` | public | Moderate and blur one photo now, and hand back a handle for it. |
| GET | `/api/open311/v2/public/requests` | public | Public endpoint - List all requests WITHOUT personal information (cached) |
| GET | `/api/open311/v2/public/requests/{request_id}` | public | Get full public request details including media - for detail view |
| GET | `/api/open311/v2/public/requests/{request_id}/audit-log` | public | Get public audit log for a request - shows status changes only, no internal details. |
| GET | `/api/open311/v2/public/requests/{request_id}/comments` | public | Get external/public comments for a request - no auth required. |
| POST | `/api/open311/v2/public/requests/{request_id}/comments` | public | Add a public comment to a request - no auth required, always external visibility |
| GET | `/api/open311/v2/requests.json` | staff | Open311 v2 compatible - List service requests (staff only) |
| POST | `/api/open311/v2/requests.json` | public | Open311 v2 compatible - Create a new service request (public) |
| GET | `/api/open311/v2/requests/asset/{asset_id}/related` | staff | Get all requests that matched to the same asset (staff, own departments) |
| POST | `/api/open311/v2/requests/manual` | staff | Create a request from manual intake (phone, walk-in, email, other) — staff only. |
| DELETE | `/api/open311/v2/requests/{request_id}` | staff | Soft delete a service request with justification (staff/admin, own departments) |
| GET | `/api/open311/v2/requests/{request_id}.json` | staff | Get service request details (staff only, own departments) |
| POST | `/api/open311/v2/requests/{request_id}/accept-ai-priority` | staff | Accept AI-suggested priority score (staff, own departments) |
| GET | `/api/open311/v2/requests/{request_id}/audit-log` | staff | Get audit log for a request (staff only - full history) |
| GET | `/api/open311/v2/requests/{request_id}/audit-log/verify` | staff | Verify the tamper-evidence of a request's audit trail. |
| POST | `/api/open311/v2/requests/{request_id}/media/{index}/review` | staff | Publish or discard a photo the redactor could not clear (staff). |
| PATCH | `/api/open311/v2/requests/{request_id}/public-archive` | staff | Take one report off the public tracker and map, or put it back (staff). |
| POST | `/api/open311/v2/requests/{request_id}/restore` | staff | Restore a soft-deleted service request (staff/admin, own departments) |
| PUT | `/api/open311/v2/requests/{request_id}/status` | staff | Update service request status (staff only, own departments) |
| GET | `/api/open311/v2/services.json` | public | Open311 v2 compatible - List services |
| GET | `/api/open311/v2/services/{service_code}.json` | public | Open311 v2 Service Definition endpoint. |
| GET | `/api/open311/v2/tokens/{service_request_id}.json` | public | Open311 v2 Token Lookup endpoint. |

#### Platform Feedback

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/feedback/platform` | public | Record one anonymous answer. Public (resident-facing), by design. |
| GET | `/api/feedback/platform/statistics` | staff | The distribution, for the statistics page. Staff only. |

#### Provisioning (orchestrator)

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/provisioning/bootstrap` | orchestrator-token | Replace the interactive first-run flow when the panel creates a town: |
| POST | `/api/provisioning/break-glass` | public | Exchange a panel-issued break-glass token for a time-boxed admin JWT. |
| POST | `/api/provisioning/host-secrets` | orchestrator-token | Accept provider credentials the deployment's host supplies for this town. |
| POST | `/api/provisioning/lifecycle` | orchestrator-token | Panel-set suspend/resume (A7). While suspended the API returns 503 for |
| POST | `/api/provisioning/managed-settings` | orchestrator-token | Apply state-set managed policy pushed by the orchestrator (A-plan). |

#### Research Suite

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/research/access-logs` | researcher | Get research access audit logs (admin only) |
| GET | `/api/research/analytics` | researcher | Get aggregate analytics (no PII exposed) |
| POST | `/api/research/chat` | researcher | Conversational AI assistant — answers questions about |
| GET | `/api/research/code-snippets` | researcher | Get R and Python code snippets for fetching and analyzing data |
| GET | `/api/research/data-dictionary` | researcher | Get data dictionary explaining all fields in exports. |
| GET | `/api/research/export/csv` | researcher | Export sanitized request data as CSV for research analysis. |
| GET | `/api/research/export/data-dictionary` | researcher | Download data dictionary as CSV file. |
| GET | `/api/research/export/geojson` | researcher | Export sanitized request data as GeoJSON for GIS analysis. |
| GET | `/api/research/packs` | admin | Pack switch metadata for the Admin Console toggles. |
| GET | `/api/research/status` | researcher | Check if Research Suite is enabled |

#### Resident History

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/resident-history/requests/{service_request_id}` | staff | Other reports from the same email address as this report. |
| POST | `/api/resident-history/search` | staff | Reports filed under one full email address, or one full name. |

#### Roads

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/road-check` | public | Would a report here be redirected, and which road decided that? |
| POST | `/api/roads/config-check` | staff | Problems in a routing config, before it is saved. |
| POST | `/api/roads/corridor-check` | staff | Find corridors that run alongside each other at the chosen width. |
| PUT | `/api/roads/corridor-width` | admin | How far from a centreline still counts as being on that road. |
| GET | `/api/roads/geometry` | staff | GeoJSON for the roads a clerk has selected, so they can see what a rule |
| GET | `/api/roads/search` | staff | Autocomplete for the clerk configuring which roads belong to whom. |
| POST | `/api/roads/seed` | admin | Re-seed the road network for the town boundary (admin only). |
| GET | `/api/roads/status` | admin | Read-only line for admin System Health. Never a task, just information. |

#### Services

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/services/` | public | List all active service categories (public) |
| POST | `/api/services/` | admin | Create a new service category (admin only) |
| GET | `/api/services/all` | admin | List all service categories including inactive (admin only) |
| PUT | `/api/services/reorder` | admin | Reorder service categories (admin only). Accepts {order: [{id, display_order}]}. |
| GET | `/api/services/sla-performance` | staff | SLA performance per service category (staff only). |
| DELETE | `/api/services/{service_id}` | admin | Delete service category (admin only) |
| GET | `/api/services/{service_id}` | public | Get service by ID (only returns active services for public access) |
| PUT | `/api/services/{service_id}` | admin | Update service category with routing configuration (admin only) |
| PATCH | `/api/services/{service_id}/toggle` | admin | Toggle service active status (admin only) |

#### Setup

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/setup/auth0/configure` | admin | Automatically configure Auth0 tenant. |
| POST | `/api/setup/backup-key` | admin | Generate the backup passphrase, store it, and return it once. |
| POST | `/api/setup/gcp/configure` | admin | Configure Google Cloud Platform. |
| POST | `/api/setup/reencrypt-pii` | admin | Re-wrap PII onto the current key immediately, instead of waiting. |
| GET | `/api/setup/status` | admin | Get current setup status. |
| GET | `/api/setup/storage-status` | admin | What, if anything, is not yet on the storage this town has chosen. |
| POST | `/api/setup/verify` | admin | Verify current Auth0 and GCP configuration. |

#### System

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/sentry-debug` | public | Test endpoint to verify Sentry integration. Only available in debug mode. |
| GET | `/api/system/advanced-statistics` | staff | Advanced statistics, with the reason written down when it cannot build them. |
| GET | `/api/system/ai/catalog` | admin | AI provider catalog for the admin UI: available boundaries (Vertex / |
| POST | `/api/system/ai/models/refresh` | admin | Live-discover a provider's current models and update the shared cache. |
| POST | `/api/system/analytics-chat` | staff | Conversational AI analytics — chat with Vertex AI about all system data. |
| GET | `/api/system/backups` | admin | List all available database backups |
| POST | `/api/system/backups/cleanup` | admin | Clean up old backups based on retention policy |
| POST | `/api/system/backups/create` | admin | Trigger a manual database backup |
| GET | `/api/system/backups/status` | admin | Get backup system status including configuration and last backup |
| POST | `/api/system/backups/test` | admin | Check the backup settings for real: storage round trip and passphrase. |
| DELETE | `/api/system/backups/{backup_name}` | admin | Delete a specific backup |
| POST | `/api/system/backups/{backup_name}/restore` | admin | Restore database from a backup. |
| PUT | `/api/system/capabilities` | admin | Record which integrations the town wants, credentials aside. |
| GET | `/api/system/client-errors` | admin | Browser crashes residents and staff have hit. |
| POST | `/api/system/client-errors` | public | Record a browser-side error report (public; default rate limit). |
| GET | `/api/system/config` | public | Deployment-mode flags (public). The setup UI uses managed_mode to show |
| GET | `/api/system/connectors/health` | admin | What each integration is actually doing, as opposed to whether its |
| POST | `/api/system/connectors/{connector}/mute` | admin | "I know about this one." Stops the emails; leaves the badge alone. |
| GET | `/api/system/current-version` | admin | Get current git version information (admin only). |
| POST | `/api/system/disclaimer/acknowledge` | public | Log that a user has acknowledged the non-emergency disclaimer. |
| POST | `/api/system/domain/configure` | admin | Point the town's own domain at this deployment, and make Caddy serve it. |
| GET | `/api/system/domain/status` | admin | Get current domain configuration status |
| GET | `/api/system/health-dashboard` | admin | Comprehensive system health dashboard for non-technical administrators. |
| GET | `/api/system/heatmap-data` | staff | Return two sets of weighted coordinates for spatial bias detection: |
| GET | `/api/system/identity/catalog` | admin | Identity provider catalog for the admin UI (Auth0 / Entra / Okta / OIDC), |
| GET | `/api/system/maps/catalog` | admin | Map provider catalog. Maps is a capability like AI or translation, so it |
| GET | `/api/system/providers/cloud-identity` | admin | Whether this server already has an identity on its cloud. |
| GET | `/api/system/providers/cloud-profile` | admin | Report the current cloud environment: the matched profile (or 'mixed'), |
| POST | `/api/system/providers/cloud-profile` | admin | Apply a whole cloud environment in one choice: sets the AI, translation and |
| GET | `/api/system/providers/status` | admin | Which provider each capability is on, and which providers are set up. |
| POST | `/api/system/providers/{capability}/save` | admin | Select a provider for a capability and save its settings/secrets. |
| POST | `/api/system/providers/{capability}/test` | admin | Live connectivity check for the currently-configured provider of a |
| GET | `/api/system/releases` | admin | Fetch available releases from GitHub (admin only). |
| GET | `/api/system/releases/{ref}/security` | admin | Fetch security verification status for a specific release/commit (admin only). |
| GET | `/api/system/retention/export` | admin | Export records in answer to a public-records request. |
| GET | `/api/system/retention/export/fields` | admin | What a records custodian can choose to include, and what is sensitive. |
| GET | `/api/system/retention/legal-hold` | admin | Get all requests currently under legal hold. |
| GET | `/api/system/retention/policy` | admin | Get current retention policy configuration. |
| POST | `/api/system/retention/policy` | admin | Update retention policy configuration (admin only). |
| GET | `/api/system/retention/preview` | admin | What pressing "Run now" would actually do. |
| POST | `/api/system/retention/run` | admin | Run retention enforcement now. |
| POST | `/api/system/runbook/{action}` | admin | Execute emergency runbook actions (admin only). |
| GET | `/api/system/secrets` | admin | Every secret this town has, and whether it is really there. |
| POST | `/api/system/secrets` | admin | Create or update a secret (admin only) - values are encrypted at rest and stored in Secret Manager |
| POST | `/api/system/secrets/migrate-encryption` | admin | Migrate existing plaintext secrets to encrypted format. |
| POST | `/api/system/secrets/migrate-to-secret-manager` | admin | Migrate all configured secrets from database to Google Secret Manager. |
| GET | `/api/system/secrets/store` | admin | Where this town's credentials are kept, and whether anyone said so. |
| POST | `/api/system/secrets/store` | admin | Record where this town's credentials go. Once, deliberately. |
| POST | `/api/system/secrets/sync` | admin | Add any missing secrets from the default list (admin only) |
| GET | `/api/system/settings` | public | Get system settings (public - for branding) |
| POST | `/api/system/settings` | admin | Update system settings (admin only) |
| GET | `/api/system/setup/state` | admin | Whether anybody has said this town is set up. |
| POST | `/api/system/setup/state` | admin | "I am done here." Said by a person, because nothing else can say it. |
| GET | `/api/system/statistics` | staff | Request counts by status and category, plus the ten newest requests. |
| GET | `/api/system/statistics/redirected` | staff | How many residents were redirected instead of filing, and to whom. |
| POST | `/api/system/switch-version` | admin | Production-grade version deployment with automatic rollback. |
| GET | `/api/system/timezone` | admin | Which clock the console shows times on. |
| POST | `/api/system/timezone` | admin | Set the town's IANA timezone (admin only). |
| POST | `/api/system/translate/auto` | admin | Auto-translate an object (dictionary) to multiple languages (admin only). |
| POST | `/api/system/translate/batch` | public | Batch translate multiple UI strings (public endpoint). |
| POST | `/api/system/translate/health` | admin | Check if Google Cloud Translation API key is configured (admin only) |
| GET | `/api/system/translate/languages` | public | Get list of supported languages (public) |
| POST | `/api/system/translate/suggest` | admin | Auto-translate text using LibreTranslate (admin only). |
| GET | `/api/system/translation/catalog` | admin | Translation provider catalog (Google / Azure) + current selection. |
| POST | `/api/system/update` | admin | Pull updates from GitHub (admin only). Code changes reload automatically. |
| POST | `/api/system/upload/image` | staff | Upload an image file (staff only). Returns the URL to access it. |

#### Telemetry (orchestrator)

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/telemetry` | orchestrator-token | Usage and health counters for the hosting panel (orchestrator only). |

#### Users

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/users/` | admin | List all users (admin only) |
| POST | `/api/users/` | admin | Create a new user (admin only). |
| GET | `/api/users/me/notification-preferences` | staff | Get current user's notification preferences |
| PUT | `/api/users/me/notification-preferences` | staff | Update current user's notification preferences |
| GET | `/api/users/staff` | staff | List staff and admin users for assignment (accessible by any staff user) |
| DELETE | `/api/users/{user_id}` | admin | Delete user (admin only) |
| GET | `/api/users/{user_id}` | admin | Get user by ID (admin only) |
| PUT | `/api/users/{user_id}` | admin | Update user (admin only) |
| POST | `/api/users/{user_id}/reset-password-json` | admin | Reset user password via JSON body (admin only) |
