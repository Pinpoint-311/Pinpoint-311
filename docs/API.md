# Pinpoint 311 — API Reference

> **Base URL**: `https://<your-domain>/api`
>
> **Standard**: [Open311 GeoReport v2](http://wiki.open311.org/GeoReport_v2)
>
> **Format**: All endpoints accept and return `application/json`

---

## Table of Contents

- [Authentication](#authentication)
- [Public APIs (No Authentication Required)](#public-apis-no-authentication-required)
  - [Open311 v2 Standard](#open311-v2-standard)
  - [Public Request Portal](#public-request-portal)
  - [Services & GIS](#services--gis)
  - [System](#system)
- [Authenticated APIs](#authenticated-apis-jwt-required)
  - [Staff Endpoints](#staff-endpoints)
  - [Admin Endpoints](#admin-endpoints)
  - [Research Endpoints](#research-endpoints)
- [Rate Limiting](#rate-limiting)
- [Security Model](#security-model)
- [Error Responses](#error-responses)

---

## Authentication

Pinpoint 311 uses **JWT Bearer tokens** for authentication. Tokens are issued via Auth0 SSO or the bootstrap flow (first-time setup only).

### Obtaining a Token

#### Via Auth0 SSO (Production)
```
GET /api/auth/login?redirect_uri=https://your-domain.com/callback
```
Returns `{ "auth_url": "https://your-auth0-domain/authorize?..." }`. Redirect the user to `auth_url`. After authentication, Auth0 redirects back with a JWT token.

#### Via Demo Mode (Development)
```
GET /api/auth/demo-login
```
Only available when `DEMO_MODE=true`. Returns HTML that stores a JWT in localStorage.

### Using a Token

Include the JWT in the `Authorization` header:
```
Authorization: Bearer <your-jwt-token>
```

### Token Info
```
GET /api/auth/me
```
Returns the current user's profile (id, username, email, role, departments).

---

## Public APIs (No Authentication Required)

These endpoints are accessible without any authentication. They are designed for resident-facing applications and third-party integrations.

> **Privacy Note**: All public endpoints strip personally identifiable information (PII). No resident names, emails, phone numbers, or staff usernames are ever exposed.

---

### Open311 v2 Standard

#### Discovery
```
GET /api/open311/v2/discovery.json
```
API metadata and capability advertisement per the Open311 v2 specification.

**Response:**
```json
{
  "changeset": "2026-03-31T00:00:00Z",
  "contact": "You may email support@pinpoint311.org for any questions or issues.",
  "key_service": "https://your-domain/api/auth/login",
  "type": "production",
  "endpoints": [
    {
      "specification": "http://wiki.open311.org/GeoReport_v2",
      "url": "https://your-domain/api/open311/v2",
      "changeset": "2026-03-31T00:00:00Z",
      "type": "production",
      "formats": ["application/json"]
    }
  ],
  "extensions": {
    "public_portal": { "description": "Public request tracking with PII redaction", "..." : "..." },
    "ai_triage": { "description": "Automated Vertex AI priority scoring on submission", "..." : "..." },
    "asset_linking": { "description": "Link requests to infrastructure assets", "..." : "..." }
  }
}
```

---

#### List Services
```
GET /api/open311/v2/services.json
```
Returns all active service categories that residents can submit requests for.

**Response:**
```json
[
  {
    "service_code": "POTHOLE",
    "service_name": "Pothole Repair",
    "description": "Report road damage or potholes",
    "type": "realtime",
    "keywords": "pothole repair",
    "group": "municipal"
  }
]
```

---

#### Service Definition
```
GET /api/open311/v2/services/{service_code}.json
```
Returns the extended attributes (form fields) for a specific service type. External clients can use this to dynamically build intake forms.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `service_code` | string | The service code (e.g., `POTHOLE`, `NOISE`) |

**Response:**
```json
{
  "service_code": "POTHOLE",
  "service_name": "Pothole Repair",
  "description": "Report road damage or potholes",
  "metadata": true,
  "type": "realtime",
  "attributes": [
    {
      "variable": true,
      "code": "description",
      "datatype": "text",
      "required": true,
      "datatype_description": "Detailed description of the issue (min 10 chars)",
      "order": 1,
      "description": "Please describe the issue"
    },
    {
      "variable": true,
      "code": "address",
      "datatype": "string",
      "required": false,
      "order": 2,
      "description": "Location address"
    },
    {
      "variable": true,
      "code": "email",
      "datatype": "string",
      "required": true,
      "order": 5,
      "description": "Contact email"
    }
  ],
  "routing_mode": "township",
  "translations_available": ["en", "es"],
  "departments": ["Public Works"]
}
```

---

#### Submit a Service Request
```
POST /api/open311/v2/requests.json
```
Submit a new service request (report an issue). This is the primary intake endpoint.

**Rate Limit**: `10 requests/minute per IP`

**Request Body:**
```json
{
  "service_code": "POTHOLE",
  "description": "Large pothole on Main Street near the intersection with Oak Ave. About 2 feet wide.",
  "address": "123 Main St, Springfield, IL 62701",
  "lat": 39.7817,
  "long": -89.6501,
  "email": "resident@example.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "phone": "555-0100",
  "media_urls": ["data:image/jpeg;base64,..."],
  "preferred_language": "en"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `service_code` | string | ✅ | Must match an active service code |
| `description` | string | ✅ | Min 10 characters |
| `email` | string | ✅ | Valid email address |
| `address` | string | | Street address |
| `lat` | float | | Latitude |
| `long` | float | | Longitude |
| `first_name` | string | | |
| `last_name` | string | | |
| `phone` | string | | |
| `media_urls` | string[] | | Up to 3 photo URLs or base64-encoded images |
| `preferred_language` | string | | ISO 639-1 code (default: `en`) |

**Response** (`201 Created`):
```json
{
  "id": 42,
  "service_request_id": "REQ-20260331-A1B2C3D4",
  "service_code": "POTHOLE",
  "service_name": "Pothole Repair",
  "status": "open",
  "priority": 5,
  "requested_datetime": "2026-03-31T12:00:00Z",
  "..."
}
```

> **Note**: The `service_request_id` is the resident's tracking token. They can use this with the Token Lookup endpoint to check status anonymously.

---

#### Token Lookup (Track a Request)
```
GET /api/open311/v2/tokens/{service_request_id}.json
```
Allows a resident to check the status of their request using only the service request ID they received at submission. **No account or authentication required.**

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `service_request_id` | string | The tracking ID (e.g., `REQ-20260331-A1B2C3D4`) |

**Response:**
```json
{
  "service_request_id": "REQ-20260331-A1B2C3D4",
  "status": "in_progress",
  "status_notes": null,
  "service_code": "POTHOLE",
  "service_name": "Pothole Repair",
  "description": "Large pothole on Main Street...",
  "address": "123 Main St, Springfield, IL 62701",
  "lat": 39.7817,
  "long": -89.6501,
  "requested_datetime": "2026-03-31T12:00:00Z",
  "updated_datetime": "2026-03-31T14:30:00Z",
  "closed_substatus": null,
  "media_urls": [],
  "completion_photo_url": null,
  "token": "REQ-20260331-A1B2C3D4"
}
```

**Privacy**: This endpoint returns the request description and location but **never** returns the submitter's name, email, or phone.

---

### Public Request Portal

These endpoints power the Resident Portal's public transparency view.

#### List All Requests (Public)
```
GET /api/open311/v2/public/requests
```
Returns all non-deleted requests with PII stripped. Optimized with 60-second Redis cache.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | all | Filter: `open`, `in_progress`, `closed` |
| `service_code` | string | all | Filter by service category |
| `limit` | int | unlimited | Max results |
| `offset` | int | 0 | Pagination offset |

**Response:**
```json
[
  {
    "service_request_id": "REQ-20260331-A1B2C3D4",
    "service_code": "POTHOLE",
    "service_name": "Pothole Repair",
    "description": "Large pothole on Main Street...",
    "status": "open",
    "address": "123 Main St, Springfield, IL 62701",
    "lat": 39.7817,
    "long": -89.6501,
    "requested_datetime": "2026-03-31T12:00:00Z",
    "updated_datetime": "2026-03-31T14:30:00Z",
    "photo_count": 2,
    "has_completion_photo": false
  }
]
```

> **Performance Note**: Media data is excluded from list responses. Use the detail endpoint to fetch full photos.

---

#### Get Request Detail (Public)
```
GET /api/open311/v2/public/requests/{request_id}
```
Returns full public details including media attachments, department assignment (name only), and completion info.

---

#### Get Comments
```
GET /api/open311/v2/public/requests/{request_id}/comments
```
Returns all **external** (public-facing) comments on a request. Internal staff comments are never exposed.

---

#### Post a Comment
```
POST /api/open311/v2/public/requests/{request_id}/comments
```
Add an anonymous public comment to a request.

**Rate Limit**: `5 comments/minute per IP`

**Request Body:**
```json
{
  "content": "I noticed this pothole has gotten bigger since last week."
}
```

The comment will be attributed to **"Resident"** (anonymous).

---

#### Get Audit Log (Public)
```
GET /api/open311/v2/public/requests/{request_id}/audit-log
```
Returns the status change history. Staff usernames are redacted to **"Staff"** for privacy.

**Response:**
```json
[
  {
    "id": 1,
    "action": "submitted",
    "old_value": null,
    "new_value": "open",
    "actor_type": "resident",
    "actor_name": "Resident",
    "created_at": "2026-03-31T12:00:00Z"
  },
  {
    "id": 2,
    "action": "status_change",
    "old_value": "open",
    "new_value": "in_progress",
    "actor_type": "staff",
    "actor_name": "Staff",
    "created_at": "2026-03-31T14:30:00Z"
  }
]
```

---

### Services & GIS

#### List Active Services
```
GET /api/services/
```
Returns all active service categories with department associations. Used by the resident portal to render the intake form.

---

#### Geocode Address
```
GET /api/gis/geocode?address=123+Main+St+Springfield+IL
```
Forward geocoding — converts an address to lat/lng coordinates.

---

#### Reverse Geocode
```
GET /api/gis/reverse-geocode?lat=39.7817&lng=-89.6501
```
Converts coordinates to a street address.

---

#### Get Boundaries
```
GET /api/gis/boundaries
```
Returns all published boundary geometries (township limits, zones) for map rendering.

---

#### Check Boundary
```
GET /api/gis/check-boundary?lat=39.7817&lng=-89.6501
```
Checks whether a location falls within the municipality's service boundary.

---

### System

#### Get System Settings (Branding)
```
GET /api/system/settings
```
Returns public system configuration: township name, logo URL, hero text, primary color, social links. Used by the frontend for branding.

---

#### Acknowledge Disclaimer
```
POST /api/system/disclaimer/acknowledge
```
Records that a resident has accepted the legal disclaimer. Required before submitting a request.

---

#### Get Translation Languages
```
GET /api/system/translate/languages
```
Returns the list of supported languages for service name/description translations.

---

#### Health Check (Quick)
```
GET /api/health/quick
```
Simple liveness probe. Returns `{"status": "ok"}` if the API is running. Intended for monitoring/load balancers.

---

#### Auth Status
```
GET /api/auth/status
```
Returns whether Auth0 SSO is configured. Used by the login page to determine the authentication flow.

---

## Authenticated APIs (JWT Required)

All endpoints below require a valid JWT token in the `Authorization: Bearer <token>` header.

### Staff Endpoints

**Required Role**: `staff` or `admin`

#### List All Requests (Full)
```
GET /api/open311/v2/requests.json
```
Returns all requests with **full PII** (names, emails, phones) and assignment details. This is the staff management view.

---

#### Get Request Detail (Full)
```
GET /api/open311/v2/requests/{request_id}.json
```
Returns complete request details including PII, AI analysis, staff notes, assignment, and audit trail.

---

#### Update Request Status
```
PUT /api/open311/v2/requests/{request_id}/status
```
Update status, priority, assignment, or close a request.

**Request Body:**
```json
{
  "status": "in_progress",
  "assigned_department_id": 1,
  "assigned_to": "jsmith",
  "priority": 8,
  "staff_notes": "Dispatching crew tomorrow morning"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `open`, `in_progress`, `closed` |
| `priority` | int (1-10) | Manual priority override |
| `assigned_department_id` | int | Department assignment |
| `assigned_to` | string | Staff username |
| `staff_notes` | string | Internal notes |
| `closed_substatus` | string | `resolved`, `no_action`, `third_party` |
| `completion_message` | string | Public-facing completion note |
| `completion_photo_url` | string | Before/after photo |
| `flagged` | bool | **Admin only** — legal hold |

---

#### Create Manual Request
```
POST /api/open311/v2/requests/manual
```
Create a request from a phone call, walk-in, or email. Does not require resident email.

**Request Body:**
```json
{
  "service_code": "POTHOLE",
  "description": "Caller reports pothole on Oak Avenue",
  "address": "456 Oak Ave",
  "first_name": "John",
  "last_name": "Smith",
  "phone": "555-0200",
  "source": "phone"
}
```

---

#### Delete Request (Soft)
```
DELETE /api/open311/v2/requests/{request_id}
```
Soft-deletes a request. Requires a justification.

**Request Body:**
```json
{
  "justification": "Duplicate of REQ-20260331-ABCDEF12 — same issue reported twice"
}
```

---

#### Restore Deleted Request
```
POST /api/open311/v2/requests/{request_id}/restore
```

---

#### Accept AI Priority Suggestion
```
POST /api/open311/v2/requests/{request_id}/accept-ai-priority
```
Formalizes a machine-generated priority score into the request's authoritative priority. Maintains human-in-the-loop accountability.

---

#### Get Full Audit Log
```
GET /api/open311/v2/requests/{request_id}/audit-log
```
Returns the complete audit trail with staff usernames (not redacted like the public version).

---

#### Related Requests by Asset
```
GET /api/open311/v2/requests/asset/{asset_id}/related?exclude_request_id=REQ-123
```
Finds all requests linked to the same infrastructure asset (e.g., same fire hydrant, same streetlight).

---

#### List Departments
```
GET /api/departments/
```
Returns all active departments with routing emails.

---

#### Statistics
```
GET /api/system/statistics
```
Returns summary counts and recent requests for the staff dashboard.

---

#### Advanced Statistics
```
GET /api/system/advanced-statistics
```
Returns comprehensive analytics: temporal patterns, geospatial hotspots, department metrics, workload distribution, predictive insights, cost estimates, and resolution trends.

---

#### Analytics Chat (AI)
```
POST /api/system/analytics-chat
```
Conversational AI powered by Vertex AI. Analyzes all system data (excluding resident PII) to answer questions about trends, performance, and patterns.

**Request Body:**
```json
{
  "message": "What are the most common issues this month?",
  "conversation_history": []
}
```

---

#### Upload Image
```
POST /api/system/upload/image
```
Upload a photo attachment (multipart form data). Returns the stored URL.

---

#### Staff List
```
GET /api/users/staff
```
Returns all staff members for assignment dropdowns.

---

#### Notification Preferences
```
GET /api/users/me/notification-preferences
PUT /api/users/me/notification-preferences
```
Get/update the current user's email and SMS notification settings.

---

### Admin Endpoints

**Required Role**: `admin`

#### User Management
```
GET    /api/users/           # List all users
POST   /api/users/           # Create user
GET    /api/users/{id}       # Get user
PUT    /api/users/{id}       # Update user
DELETE /api/users/{id}       # Delete user
POST   /api/users/{id}/reset-password
```

---

#### Service Management
```
GET    /api/services/all     # List all (including inactive)
POST   /api/services/        # Create service
PUT    /api/services/{id}    # Update service
DELETE /api/services/{id}    # Delete service
PATCH  /api/services/{id}/toggle  # Enable/disable
PUT    /api/services/reorder      # Reorder display
```

---

#### Department Management
```
POST   /api/departments/     # Create department
DELETE /api/departments/{id} # Delete department
```

---

#### System Configuration
```
POST /api/system/settings         # Update branding/settings
GET  /api/system/secrets          # List configured secrets
POST /api/system/secrets          # Set a secret
GET  /api/system/retention        # Get retention policy
POST /api/system/retention        # Update retention policy
```

---

#### Audit Logs
```
GET /api/audit/logs                # Query audit logs
GET /api/audit/stats               # Audit statistics
GET /api/audit/export              # Export logs (CSV)
GET /api/audit/verify-integrity    # Verify audit chain integrity
```

---

#### System Health
```
GET  /api/health/                  # Full health check (all integrations)
GET  /api/health/uptime/history    # Uptime history (24h-7d)
GET  /api/health/uptime/stats      # Uptime percentages
POST /api/health/uptime/check-now  # Trigger manual health check
```

---

#### Backups & Updates
```
GET    /api/system/backups         # List backups
POST   /api/system/backups         # Create backup
DELETE /api/system/backups/{id}    # Delete backup
GET    /api/system/current-version # Current deployment version
GET    /api/system/releases        # Available releases
POST   /api/system/update          # Trigger system update
POST   /api/system/switch-version  # Switch to specific version
```

---

#### GIS Administration
```
POST /api/gis/boundaries           # Upload boundary
GET  /api/gis/census-boundary-search  # Search Census TIGER
POST /api/gis/boundaries/save-census  # Import Census boundary
GET  /api/gis/osm/search           # Search OpenStreetMap
POST /api/gis/township-boundary    # Set township boundary
```

---

#### Translation Management
```
POST /api/system/translate/health   # Test translation API
POST /api/system/translate/suggest  # AI-generate translations
POST /api/system/translate/auto     # Auto-translate a service
POST /api/system/translate/batch    # Batch translate all services
```

---

#### Map Layer Management
```
GET    /api/map-layers/            # List all layers
POST   /api/map-layers/            # Create layer
PUT    /api/map-layers/{id}        # Update layer
DELETE /api/map-layers/{id}        # Delete layer
```

---

#### Domain & Infrastructure
```
POST /api/system/domain/configure  # Configure custom domain
GET  /api/system/domain/status     # Domain status
POST /api/system/runbook/{action}  # Execute runbook action
GET  /api/system/health-dashboard  # Infrastructure dashboard
```

---

### Research Endpoints

**Required Role**: `researcher` or `admin`

The research suite provides anonymized, aggregate data for academic analysis.

```
GET  /api/research/analytics       # Anonymized analytics
GET  /api/research/export          # Data export (CSV/JSON)
POST /api/research/chat            # AI research assistant
```

---

## Rate Limiting

Rate limits are enforced per IP address using [SlowAPI](https://github.com/laurentS/slowapi).

| Endpoint | Limit |
|----------|-------|
| `POST /api/open311/v2/requests.json` | **10 requests/minute** per IP |
| `POST /api/open311/v2/public/requests/{id}/comments` | **5 comments/minute** per IP |
| All other endpoints | **500 requests/minute** (global) |

Exceeding the limit returns `429 Too Many Requests`.

---

## Security Model

### Role-Based Access Control (RBAC)

| Role | Access Level |
|------|-------------|
| **Public** | Submit requests, view public data, track by token |
| **Staff** | All public + view PII, update requests, manage assignments |
| **Admin** | All staff + user management, system config, audit, backups |
| **Researcher** | Anonymized analytics and data export |

### PII Protection
- All public endpoints strip names, emails, phone numbers
- Staff usernames are redacted to "Staff" in public audit logs
- Internal comments are never exposed publicly
- PII fields are encrypted at rest using Google Cloud KMS or Fernet fallback

### Infrastructure Security
- JWT tokens with configurable expiration
- Auth0 SSO with CSRF state validation
- All API traffic over HTTPS (enforced by Caddy reverse proxy)
- Security headers middleware (CSP, HSTS, X-Frame-Options)
- Input sanitization for all user-supplied fields

---

## Error Responses

All errors follow a consistent format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status Code | Meaning |
|-------------|---------|
| `400` | Bad Request — invalid input or validation failure |
| `401` | Unauthorized — missing or invalid JWT token |
| `403` | Forbidden — insufficient role/permissions |
| `404` | Not Found — resource doesn't exist |
| `429` | Too Many Requests — rate limit exceeded |
| `500` | Internal Server Error |

---

## Interactive API Documentation

When running, interactive Swagger UI documentation is available at:

```
https://<your-domain>/api/docs
```

ReDoc documentation is available at:

```
https://<your-domain>/api/redoc
```
