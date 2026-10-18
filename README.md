# Pinpoint 311

<p align="center">
  <img src="frontend/public/pinpoint311_logo_light.png" alt="Pinpoint 311" height="60">
</p>
<p align="center">
  <a href="https://pinpoint311.org"><img src="https://img.shields.io/badge/Website-pinpoint311.org-6366f1.svg" alt="Website"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://hcb.hackclub.com/pinpoint-311"><img src="https://img.shields.io/badge/Fiscal%20Sponsor-Hack%20Club-ec3750.svg" alt="Fiscally Sponsored by Hack Club"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/build-publish.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/build-publish.yml/badge.svg" alt="Build status"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/accessibility.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/accessibility.yml/badge.svg" alt="Accessibility audit"></a>
</p>

Pinpoint 311 is open-source, self-hosted 311 software for small and mid-size
municipalities. Residents report non-emergency problems (a pothole, a broken
streetlight, a missed trash pickup) from a phone or computer without creating an
account. Staff triage, route, and close those reports from one dashboard.
Administrators configure the whole system from a browser.

The town runs it on its own server and owns the database. It is MIT-licensed and
has no per-seat or per-request fees. Cloud services such as AI, translation, and
text messaging are optional; each one is switched on and configured in the Admin
Console, and the platform keeps working when any of them is off or unreachable.

This README has two audiences:

- **Town IT staff deploying it**: read [Quick start](#quick-start), [Configuration](#configuration), [Security model](#security-model), and [Operations](#operations).
- **Developers contributing**: read [Architecture](#architecture) and [Development and tests](#development-and-tests).

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Security model](#security-model)
- [Operations](#operations)
- [Integrations with town systems](#integrations-with-town-systems)
- [API](#api)
- [Development and tests](#development-and-tests)
- [Centralized hosting (optional)](#centralized-hosting-optional)
- [Accessibility](#accessibility)
- [Reporting security vulnerabilities](#reporting-security-vulnerabilities)
- [Further documentation](#further-documentation)
- [License and fiscal sponsorship](#license-and-fiscal-sponsorship)

---

## Features

### Resident portal (`/`)

- Report without an account. Pick a category, drop a map pin or type an address, describe the problem, and attach up to three photos.
- Track a report through a private link, with email and text updates if the resident gives an email address or phone number.
- Public map and list of community reports, with personal details removed. Residents can mark their own report as unlisted when the Unlisted Reports module is on.
- The interface, categories, and resident-submitted text can be shown in more than 100 languages through the configured translation provider.
- A one-time non-emergency notice and a persistent "call 911 for emergencies" banner. Each acknowledgment is recorded.
- Editable Privacy Policy, Terms of Service, and Accessibility Statement pages (`/privacy`, `/terms`, `/accessibility`).

### Photo and content safety

- Photos are screened before submission. Faces and license plates are blurred and EXIF metadata (including GPS) is stripped before a photo is stored. Detection runs on Google Cloud Vision, AWS Rekognition, Azure AI, or an offline local detector (OpenCV and Tesseract). Photos the detector is unsure about are held for staff review instead of being published. Detection is a mitigation, not a guarantee.
- Descriptions and public comments are screened for abusive content. Explicit content is blocked; other flagged content goes through and is marked for staff.

### Staff dashboard (`/staff`)

- One queue with list, map, and detail views, filters by status, priority, department, category, and date, and department scoping: non-admin staff see reports routed to their departments, reports assigned to them, and unrouted reports that still need triage.
- Internal notes and public comments, status changes, assignment, and closing as resolved (optionally with a completion photo), no action needed, or transferred to a third party.
- **Priority is one number from 1 to 10.** When AI is on, it suggests a priority; staff can accept or change it, and every change is recorded in the audit log.
- **Triage panel.** Nearby similar reports, proximity to schools, hospitals, and other critical sites, current weather, and asset history are computed from your own data without AI. When AI is on, it adds a plain-language summary, a suggested priority, and safety flags. AI never routes, assigns, or closes a report.
- **Manual intake.** Staff can log a report taken by phone, email, in person, or another channel. It runs through the same routing, notifications, triage, and connector pushes as a resident submission, and the channel is recorded. Blank optional fields are left blank; no placeholder contact details are invented.
- **Resident history (optional module).** Shows staff a resident's other reports and lets them search by full email address or full name. Matching uses keyed fingerprints, so the encrypted contact fields are never decrypted to search. Results are limited to reports the staff member could already open and show only ID, category, status, and date. Every lookup is audited; if the audit record cannot be written, no results are returned.
- **Analytics Advisor.** A chat assistant that answers questions about the town's aggregated request data. It runs on the configured AI provider and is given aggregated data only, not resident contact details.
- Printable work orders with a QR code, map, and dispatch notes.
- A held-photo review queue for photos withheld by screening.

### Admin Console (`/admin`)

The console is organized into three groups, plus a **Version Control** panel in the sidebar:

| Group | Sections | What is configured there |
| --- | --- | --- |
| Branding & Setup | Branding, Setup & Integration | Town name, colors, logo, legal pages; secret store, AI, translation, email, text messaging, PII encryption, photo redaction, staff sign-in, maps, backups, crash reporting, and connections to town systems |
| Organization | Users, Departments, Service Categories | Staff accounts and roles; departments and routing emails; categories, routing rules, custom questions, icons, location mode, public visibility |
| System & Compliance | System Settings, System Health, Compliance | Feature modules, maps, municipal boundary, map layers, public archival; health checks and alert muting; records retention, legal holds, recoverable deletions, database backups |

Per-category settings:

- **Routing.** Handled by the municipality (routed to a department), third-party only (residents are shown the outside agency's contact details instead of a form), or road-based (routed by which jurisdiction maintains the road at the pin).
- **Location mode.** *Required* (a pin or address is needed to submit), *Optional* (the map is shown and can be skipped; the default), or *Not collected* (no map on the form, and any location sent anyway is discarded). The same rule applies to the resident form, staff manual intake, and inbound connectors.
- **Hide from public view.** Keeps every report in the category off the public map and list. Staff still see them.
- **Icons.** One shared set of about 110 municipal icons, grouped by topic (streets, trash and recycling, water and weather, parks, animals, code and permits, taxes and records, community and safety). The picker is searchable and suggests an icon from the category name. The same set is used on the resident form, the staff screens, and the console.
- **Custom questions.** Extra fields per category, for example "Is the dog aggressive?".

Feature modules, switched in System Settings: Research Portal, Unlisted Reports, Platform Feedback (one anonymous ease-of-use question), and Resident History.

### Research Lab (`/research`)

For staff and outside researchers with the `researcher` role, when the Research Portal module is on. It provides aggregate analytics and CSV and GeoJSON exports with a data dictionary. Exports exclude free-text descriptions and contact details, snap coordinates to a grid, and record every access. A Data Assistant chat runs on the same AI provider as triage.

### Records and retention

- Retention is set by the town's clerk in days. If it is not set, nothing is purged.
- When records expire, the town chooses between anonymizing them (removing resident details while keeping operational counts) or deleting them.
- Legal holds exempt individual records from retention.
- Soft-deleted reports can be restored by an administrator.

---

## Architecture

```
                    Internet
                       |
                 :80 / :443 (only published public ports)
                       |
                 +-----------+
                 |   Caddy   |  TLS, security headers, CSP, request size limit, access log
                 +-----------+
                  /api/*   \  everything else
                    |       \
      127.0.0.1:8000|        \127.0.0.1:5173
             +-----------+   +--------------+
             |  backend  |   |   frontend   |  nginx serving the built React app
             |  FastAPI  |   +--------------+
             +-----------+
               |      |
               |      |  enqueue
   127.0.0.1:5432     v
   +-----------+   +-------+  127.0.0.1:6379   +-------------------+
   | Postgres  |<--| Redis |<------------------|  worker           |
   | + PostGIS |   +-------+                   |  Celery + Beat    |
   +-----------+       ^                       +-------------------+
         ^             |                          |
         +-------------+--------------------------+
                                                  |
                         optional outbound calls  v
       AI, translation, email, SMS, KMS, secret store, maps, town-system connectors
```

| Service | Image or build | Role |
| --- | --- | --- |
| `db` | `ghcr.io/baosystems/postgis:15-3.3` | PostgreSQL 15 with PostGIS |
| `redis` | `redis:7-alpine` | Celery queue and caches. Runs with `noeviction` and append-only persistence so queued work survives restarts. |
| `backend` | `./backend` (Python 3.11, FastAPI) | REST API, Open311 endpoints, schema migrations on start |
| `worker` | `./backend` | Celery worker with Beat: AI triage, notifications, connector sync, health scans, backups, retention |
| `frontend` | `./frontend` (React 18, TypeScript, Vite, Tailwind; served by nginx) | Resident portal, staff dashboard, Admin Console, Research Lab |
| `caddy` | `caddy:2-alpine` | Reverse proxy and automatic HTTPS |

Code layout:

| Path | Contents |
| --- | --- |
| `backend/app/main.py` | App assembly, middleware, router registration |
| `backend/app/api/` | Route modules (auth, open311, services, system, setup, integrations, research, resident_history, health, and others) |
| `backend/app/services/` | Business logic, provider adapters, `ai/` (Vertex, Azure OpenAI, Bedrock) |
| `backend/app/integrations/` | Connector framework and connectors (Accela, ArcGIS, Open311, Tyler, generic REST) |
| `backend/app/tasks/` and `backend/app/core/celery_app.py` | Background tasks and the Beat schedule |
| `backend/app/db/migrate.py`, `backend/alembic/` | Startup migrator and Alembic revisions |
| `backend/tests/` | Pytest suite |
| `frontend/src/pages/`, `frontend/src/components/` | React pages and components, with Vitest tests alongside |
| `deploy/templates/` | Azure ARM and AWS CloudFormation templates for the cloud resources a town needs |

---

## Quick start

### Requirements

- A Linux host with Docker Engine and the Docker Compose plugin.
- 2 vCPUs and 4 GB of RAM is a reasonable starting point. The compose file sets memory limits of 2 GB each on `db`, `backend`, and `worker`, so a small host relies on those limits not all being reached at once.
- A DNS name pointing at the host if you want automatic HTTPS. Ports 80 and 443 must be reachable from the internet for certificate issuance.

### 1. Get the code and create `.env`

```bash
git clone https://github.com/Pinpoint-311/Pinpoint-311.git
cd Pinpoint-311
cp .env.example .env
```

Edit `.env` and set at least these values:

| Variable | Required | Notes |
| --- | --- | --- |
| `DB_PASSWORD` | yes | Compose refuses to start without it. |
| `SECRET_KEY` | yes | At least 32 random characters. Generate with `openssl rand -hex 32`. The backend refuses to boot with a known default or a short key. It signs staff sessions and derives the local encryption key, so do not change it casually after launch. |
| `INITIAL_ADMIN_PASSWORD` | yes | Used once, to get into the Admin Console before staff sign-in is configured. Compose refuses to start without it, and the default `admin123` is rejected. |
| `DOMAIN` | for HTTPS | The public hostname, for example `311.example.gov`. Defaults to `localhost`. |
| `TENANT_CADDY_PATH` | recommended | A host directory for Caddy site snippets written when an administrator sets a custom domain, for example `./caddy-tenants`. Set it explicitly; the compose default points at a path used by the project's own hosting. |

Everything else in `.env.example` is optional. See [Configuration](#configuration).

### 2. Review the Caddyfile

The shipped `Caddyfile` serves `{$DOMAIN}` and also contains site blocks for the
project's own demo hosts. Before going live:

- Delete every site block after the `{$DOMAIN:localhost}` block except the `import /etc/caddy/tenants/*.caddy` line.
- The `{$DOMAIN:localhost}` block includes `import noindex`, which tells search engines not to index the site. Remove that line if you want the portal to appear in search results.

### 3. Start the stack

Build from source (this is how the project's own servers run):

```bash
docker compose up -d --build
```

Or use the prebuilt multi-architecture images from GitHub Container Registry
(`ghcr.io/pinpoint-311/pinpoint-311-backend` and `-frontend`, `linux/amd64` and
`linux/arm64`):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

On first start the backend entrypoint creates the schema and seeds an initial
admin user. Check progress with:

```bash
docker compose ps
docker compose logs -f backend
```

### 4. Sign in for the first time

Until a staff identity provider is configured, the login page shows an
**Enter Admin Console** button. It opens `/api/auth/bootstrap/auto`, which asks
for `INITIAL_ADMIN_PASSWORD` and signs you in as the initial admin. From a
terminal, the equivalent is:

```bash
curl -X POST https://311.example.gov/api/auth/bootstrap -F "password=YOUR_INITIAL_ADMIN_PASSWORD"
```

The response contains a one-time `login_url` that expires after an hour.
Repeated wrong passwords from one address are locked out. Bootstrap access stops
working as soon as any identity provider (Auth0, Microsoft Entra ID, Okta, or
generic OIDC) is configured.

### 5. Finish setup in the Admin Console

Open **Admin Console > Setup & Integration**. The page lists what is configured
and what is outstanding. In order:

1. **Choose a secret store.** The page will not accept credentials until you choose where they are kept: the encrypted database, Google Secret Manager, Azure Key Vault, or AWS Secrets Manager. This is asked first so that no credential lands in a database backup before you decide.
2. **Configure staff sign-in** (Auth0, Microsoft Entra ID, Okta, or generic OIDC). Bootstrap access is disabled once this is saved.
3. **Configure a map provider** (Google Maps, Esri ArcGIS, Azure Maps, or Apple Maps) then set the municipal boundary under **System Settings** (search for the municipality to fetch its boundary polygon).
4. **Switch on and configure optional services**: AI, translation, email, text messaging, PII encryption with a cloud KMS, photo redaction, automatic backups, and crash reporting. Each card has a **Save & Test** button where a live check exists.
5. **Add users, departments, and service categories** under Organization.

---

## Configuration

Settings live in one of two places.

### Environment (`.env`, read by Docker Compose)

These are deployment-level values that must exist before the app can start or
that are shared by every town using the same build.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | db, backend, worker | Database credentials. Defaults: `township`, none, `township_db`. |
| `SECRET_KEY` | backend, worker | Session signing and local key derivation. Required. |
| `INITIAL_ADMIN_USER`, `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD` | backend | First-run admin account and bootstrap password. |
| `DOMAIN` | backend, caddy | Public hostname. |
| `ADMIN_EMAIL` | caddy | Passed to the Caddy container. The shipped Caddyfile does not reference it. |
| `RATE_LIMIT_DEFAULT` | backend | Per-client default rate limit. Default `500/minute`. |
| `GOOGLE_MAPS_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_VERTEX_PROJECT`, `GOOGLE_VERTEX_LOCATION` | backend, worker | Optional Google defaults. The same settings can be entered in the console. |
| `ACCELA_CLIENT_ID`, `ACCELA_CLIENT_SECRET`, `ACCELA_REDIRECT_URI` | backend, worker | Optional Accela developer-app credentials for OAuth sign-in. Without them the Accela wizard asks for an agency username and password. See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md). |
| `CONTACT_FORM_URL`, `CONTACT_FORM_EMBED` | backend | Optional deployment-registration form offered in the console. See the comments in `.env.example`. |
| `DB_PORT`, `REDIS_PORT`, `BACKEND_PORT`, `FRONTEND_PORT` | compose | Host ports. All four are bound to `127.0.0.1`. |
| `HTTP_PORT`, `HTTPS_PORT` | caddy | Public ports. Defaults 80 and 443. |
| `TENANT_CADDY_PATH` | backend, caddy | Directory for custom-domain site snippets. |

The backend also honors a few variables that the default compose file does not
pass through. To use them, add them to the `environment:` of the `backend` and
`worker` services in a `docker-compose.override.yml`:

| Variable | Purpose |
| --- | --- |
| `DEBUG=true` | Serves interactive API docs at `/api/docs` and `/api/redoc` and disables the strict `SECRET_KEY` check. Development only. |
| `SENTRY_DSN` | Crash-reporting DSN. Overrides the DSN saved in the console. |
| `SECRETS_PROVIDER` | Forces the secret store (`database`, `google`, `azure`, `aws`) instead of the console choice. |
| `KMS_PROVIDER` | Forces the PII key manager instead of the console choice. |
| `REQUIRE_KMS` | When true, the app refuses to write resident PII unless a cloud KMS wraps the key, instead of falling back to the local key. |

### Admin Console (stored in the database or the chosen secret store)

Everything a town administrator configures is entered in the browser:
branding, users, departments, categories, routing, retention, feature modules,
and every provider credential. Credentials are written to the chosen secret
store. With an external store (Google, Azure, AWS) the database keeps only a
reference, and a scheduled task moves any credential saved before the store was
chosen into it.

Optional services and their providers:

| Capability | Providers |
| --- | --- |
| Secret storage | Encrypted database, Google Secret Manager, Azure Key Vault, AWS Secrets Manager |
| PII encryption key | Google Cloud KMS, Azure Key Vault, AWS KMS, or an application key derived from `SECRET_KEY` |
| AI (triage, Analytics Advisor, Data Assistant) | Google Vertex AI, Azure OpenAI, AWS Bedrock. Vertex is the default. The model list is refreshed from the provider. |
| Translation | Google Cloud Translation, Azure AI Translator, Amazon Translate |
| Email | SMTP, Amazon SES, Azure Communication Services |
| Text messages | Twilio, Amazon SNS, Azure Communication Services, a generic HTTP gateway, or off |
| Photo redaction | Google Cloud Vision, AWS Rekognition, Azure AI, local (offline) |
| Content moderation | Google, Azure, or AWS moderation services, defaulting to the AI provider's cloud. A local profanity check always runs. |
| Staff sign-in | Auth0, Microsoft Entra ID, Okta, generic OIDC |
| Maps and geocoding | Google Maps, Esri ArcGIS (Online or Enterprise), Azure Maps, Apple Maps |
| Backups | Any S3-compatible object store (AWS S3, Backblaze B2, Oracle Object Storage, and others) |
| Crash reporting | Sentry |

The selected AI provider is used everywhere AI appears: request triage, photo
assessment, the staff Analytics Advisor, and the Research Lab's Data Assistant.

`deploy/templates/` contains an Azure ARM template and an AWS CloudFormation
template that create the cloud resources a town needs (see
[deploy/templates/README.md](deploy/templates/README.md)). Google has a guided
manual path on the setup page instead.

---

## Security model

### Network exposure

- Caddy is the only service published on public interfaces (ports 80 and 443).
- `db`, `redis`, `backend`, and `frontend` publish their ports on `127.0.0.1` only. Redis has no password and must stay that way. Docker's own iptables rules bypass host firewalls such as `ufw`, which is why the bindings are loopback rather than relying on a firewall.
- Caddy's admin API listens on port 2019 inside the compose network so the backend can reload it after a domain change. It is not published to the host.
- Caddy rejects request bodies over 13 MB, and the backend has a matching limit of its own.

### Docker socket

The `backend` service mounts `/var/run/docker.sock` so the in-console version
switcher can rebuild and restart containers. Access to the Docker socket is
equivalent to root on the host. Only administrators can reach the version
switcher. If you do not want in-app upgrades, remove that mount in an override
file and upgrade from the command line.

### Headers and CSP

- Caddy sets HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, and a Content-Security-Policy that allows only the map, font, and identity hosts the app uses.
- The backend sets its own headers on API responses. JSON responses get `default-src 'none'`, API responses are `Cache-Control: no-store`, and `Permissions-Policy` allows only geolocation.
- Caddy writes a JSON access log to the `caddy_data` volume and keeps it for 30 days.

### Authentication and roles

- Staff sign in through the configured identity provider, which handles MFA and passkeys. Pinpoint stores no staff passwords.
- Three roles: `staff` (works reports, scoped by department), `admin` (full access, including the Admin Console), and `researcher` (read-only access to anonymized research data).
- Rate limiting is per client address, using a forwarded address that only the trusted proxy can set. Report submission, comments, and bootstrap attempts have tighter limits.

### Encryption at rest

- **Resident PII** (name, email, phone) uses envelope encryption. Each value is encrypted with AES-256-GCM under a data key, and the data key is wrapped by Google Cloud KMS, Azure Key Vault, AWS KMS, or, when no cloud KMS is configured, a key derived from `SECRET_KEY`. A scheduled task re-wraps data keys when the key manager changes. If the cloud key is destroyed, encrypted PII cannot be recovered from any backup; see the "Losing the encryption key" section of [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md).
- **Credentials** are stored in the chosen secret store. In the database store they are encrypted with a key derived from `SECRET_KEY`.
- **Backups** are encrypted with GPG (AES-256) using a passphrase you set before they leave the server.
- Resident IP addresses recorded for abuse handling are purged on a schedule.

### Audit logging

- Every change to a service request is written to a hash-chained audit log, and the chain head is recorded daily in a separate append-only table and the application log, so a rewritten history does not pass silently.
- Every authenticated request that changes something is recorded with who, what, and when, even on endpoints that do not write their own audit entry.
- Resident-history lookups, research data access, and legal-hold changes are audited.

More detail: [COMPLIANCE.md](COMPLIANCE.md), [docs/SECURITY_PLAN.md](docs/SECURITY_PLAN.md), and [docs/PRIVACY_ASSESSMENT.md](docs/PRIVACY_ASSESSMENT.md).

---

## Operations

### Upgrades

Nothing updates itself. There are two ways to upgrade:

1. **Admin Console sidebar > Version Control.** Lists releases and recent commits, takes a database dump, checks out the chosen version, rebuilds and restarts the containers, health-checks the result, and rolls back on failure. It needs the stack to run from a git checkout and the Docker socket mount described above. It is disabled in managed mode. Use it only when this is the sole Pinpoint stack on the server using that checkout: it checks out code in the shared folder and restarts containers through the host's Docker socket, so on a server running several stacks from one checkout it would change all of them.
2. **Command line.** Take a backup first, then:

   ```bash
   git pull
   docker compose up -d --build
   ```

   or, with prebuilt images (`docker compose pull` fetches them):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```

The `backend` and `worker` containers mount `./backend` from the checkout, and
the compose file runs uvicorn without `--reload`. After changing backend code,
restart them with `docker compose restart backend worker`. The frontend is a
built image, so frontend changes need `--build`.

### Database migrations

The backend and worker entrypoint (`backend/scripts/entrypoint.sh`) runs
`python -m app.db.migrate` before starting. Under a Postgres advisory lock it:

1. Takes a `pg_dump` into the `migration_backups` volume. The newest three dumps are kept. They are unencrypted copies of the database and stay on the host.
2. Applies pending Alembic revisions that are additive.
3. Adds missing columns and widens text columns to match the models.

A migration that would drop or rewrite data is not applied automatically. The
container stops and prints the command an operator has to run. The exit codes
are distinct: `1` database unreachable, `2` destructive migration needs a human,
`3` the pre-migration dump failed so nothing was applied.

To inspect the schema state:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic heads
```

### Backups and restore

Configure **Automatic backups** on the Setup & Integration page: an
S3-compatible endpoint (a bare host such as Backblaze B2's
`s3.<region>.backblazeb2.com` is accepted), bucket, access key, secret key,
optional region, and an encryption passphrase. **Save & Test** writes, reads
back, and deletes a test object in the bucket and checks that the passphrase can
encrypt and decrypt.

- The worker takes a backup daily at 02:00 UTC: `pg_dump -Fc`, encrypted with GPG AES-256, uploaded as `db_backup_YYYYMMDD_HHMMSS.sql.gpg`.
- Old backups are removed weekly according to the records-retention setting. If retention is not configured, every backup is kept.
- Compliance > Database Backups lists backups and can create, delete, or restore one. Restore requires an explicit confirmation and overwrites the current database. It is disabled in managed mode.
- The backup contains the database only. Files staff upload through the console live in the `uploads_data` Docker volume and are not included; back that volume up separately.
- Keep the encryption passphrase somewhere other than the server. A backup cannot be restored without it.
- If PII is encrypted with a cloud KMS, a restore also needs that key to still exist.

Restore and disaster-recovery procedures are in [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md).

### Health and monitoring

- `GET /api/health/quick` needs no authentication and returns status, version, git SHA, and database revision. Use it for external uptime monitoring.
- `GET /api/health/` (admin only) checks the database, identity provider, KMS, secret store, AI, translation, and credential expiry.
- The worker runs a proactive health scan every 15 minutes (disk, memory, connections, backup age, a live KMS wrap, and more) and emails administrators about problems. Known outages can be muted for a bounded period under System Health without hiding them from the dashboard.
- Connections to town systems are checked daily, and failed syncs are retried.
- Compose health checks restart unresponsive `backend`, `worker`, and `frontend` containers, and every service uses `restart: unless-stopped`.

### Crash reporting

Paste a Sentry DSN on the **Crash reporting** card of the Setup & Integration
page. The API reads the saved DSN at startup and the worker when each worker
process starts, so restart both after saving:

```bash
docker compose restart backend worker
```

A `SENTRY_DSN` environment variable, if set, takes precedence. Events are sent
with `send_default_pii=False`, and switching crash reporting off on the setup
page drops events. See [docs/SENTRY_SETUP.md](docs/SENTRY_SETUP.md).

---

## Integrations with town systems

Pinpoint can push reports to, and pull updates from, systems a town already runs.
Connections are configured under **Setup & Integration > GovTech Platform
Connections**.

| Connector | Interface |
| --- | --- |
| Accela | Construct API v4 with OAuth2 |
| Esri ArcGIS | Feature service REST (ArcGIS Online or Enterprise) |
| Tyler Technologies | Open311 GeoReport v2 |
| Generic Open311 | Any GeoReport v2 endpoint |
| Other REST system | Configurable JSON REST client for vendors with their own API; not certified against any specific vendor |

Reports are pushed after AI triage finishes, so they carry the triaged priority.
Status changes, comments, and photos flow where the vendor's API allows it.
Priority changes are sent to Accela (once a priority mapping is set), ArcGIS
(once a priority column is mapped), and the generic REST connector (once an
update path is set). Open311 has no priority update, so priority is never sent
there. Failed syncs are retried and listed in the console.

Full setup, field mapping, and per-vendor limits: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

---

## API

Pinpoint implements the Open311 GeoReport v2 standard under `/api/open311/v2`
and a staff and admin API alongside it. The endpoint reference, authentication,
rate limits, and error format are in [docs/API.md](docs/API.md).

Interactive docs (`/api/docs`, `/api/redoc`, `/api/openapi.json`) are served
only when `DEBUG=true`, because in production they would publish a map of every
route.

---

## Development and tests

### Running locally

The default `docker-compose.yml` is also the development setup: it bind-mounts
`./backend` into the `backend` and `worker` containers. After editing backend
code, run `docker compose restart backend worker`. For frontend work with hot
reload, run Vite on the host; its dev server proxies `/api` to `http://backend:8000`,
so either run it inside the compose network or change the proxy target in
`frontend/vite.config.ts` to `http://localhost:8000` for your local session.

```bash
cd frontend
npm ci
npm run dev
```

### Backend tests

CI (`.github/workflows/backend-tests.yml`) runs Python 3.11 with the full
`requirements.txt` plus `pytest`, `pytest-asyncio`, and `aiosqlite`. The tests do
not need a running database.

On the host:

```bash
cd backend
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio aiosqlite
python -m pytest tests/ -q
```

Or inside the backend image, without installing anything on the host:

```bash
docker compose run --rm --no-deps --entrypoint bash backend \
  -c "pip install -q pytest pytest-asyncio aiosqlite && python -m pytest tests/ -q"
```

A few tests that exercise cloud provider SDKs can fail in an environment without
those providers' credentials.

### Frontend checks

CI (`.github/workflows/frontend-checks.yml`) runs on Node 20:

```bash
cd frontend
npm ci
npx tsc --noEmit -p tsconfig.json   # type check (also: npm run typecheck)
npx vitest run                      # unit, keyboard, and accessibility tests (also: npm test)
npx vite build
```

`npm run build` runs the type check before `vite build`, so the frontend Docker
image will not build with type errors. CI tolerates a small known baseline of
type errors in `src/maps/providers/azure/renderer.ts`; new errors elsewhere fail
the job.

### Schema changes

Add an Alembic revision under `backend/alembic/versions/`:

```bash
docker compose exec backend alembic revision --autogenerate -m "describe the change"
```

Additive changes apply automatically on the next start. Anything that drops or
rewrites data stops the container until an operator runs it, so write
destructive changes as a separate, deliberate revision.

### Other CI

- `build-publish.yml` builds and publishes the multi-architecture images.
- `accessibility.yml` runs axe-core against a live deployment weekly and on pushes to `main`.
- `codeql.yml` and `security-scan.yml` run CodeQL, an OWASP ZAP baseline scan, and Trivy.
- `.gitlab-ci.yml` includes GitLab's SAST template.

---

## Centralized hosting (optional)

Self-hosting is the default and is complete on its own. Centralized hosting is
for a state, county, or agency that runs separate instances for many towns. Each
town still gets its own instance, database, encryption key, and secrets; no data
is shared between towns. The orchestrator lives in a separate repository,
[Pinpoint-311/centralizedhosting](https://github.com/Pinpoint-311/centralizedhosting).

This repository contains only the hooks an instance needs to be managed, behind
the `MANAGED_MODE` setting (off by default): a token-protected provisioning and
telemetry API, version and database-revision stamps on the health endpoints,
and settings the platform owns, which appear locked in the console. In managed
mode the in-app version switcher and backup restore are disabled. With
`MANAGED_MODE` off, none of this changes behavior. Background:
[docs/VISION.md](docs/VISION.md).

---

## Accessibility

The resident portal, staff dashboard, and Admin Console are built toward WCAG 2.1
Level AA: keyboard operation, visible focus, labeled controls, and a 4.5:1
contrast target. The frontend test suite includes keyboard and screen-reader
behavior tests (`*.a11y.test.tsx`, `*.keyboard.test.tsx`), and an axe-core audit
runs in CI. This is a design target, not an independent audit or certification;
independent screen-reader testing and a third-party audit have not been done.
Each town can edit its own Accessibility Statement under Admin Console >
Branding. Details: [COMPLIANCE.md](COMPLIANCE.md#4-accessibility).

---

## Reporting security vulnerabilities

Do not open a public issue for a security vulnerability. Use GitHub's private
vulnerability reporting: open the
[Security tab](https://github.com/Pinpoint-311/Pinpoint-311/security) of this
repository and choose **Report a vulnerability**. We aim to acknowledge reports
within 48 hours.

---

## Further documentation

| Document | Contents |
| --- | --- |
| [docs/API.md](docs/API.md) | API reference |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Connectors to town systems |
| [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md) | Backup, restore, and key-loss procedures |
| [docs/SENTRY_SETUP.md](docs/SENTRY_SETUP.md) | Crash reporting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Service dependencies and data flow |
| [COMPLIANCE.md](COMPLIANCE.md) | Security posture and compliance-supporting features |
| [docs/SECURITY_PLAN.md](docs/SECURITY_PLAN.md) | System security plan |
| [docs/PRIVACY_ASSESSMENT.md](docs/PRIVACY_ASSESSMENT.md) | Privacy impact assessment |
| [COST.md](COST.md) | Hosting and cloud service cost estimates |
| [deploy/templates/README.md](deploy/templates/README.md) | Cloud resource templates |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | Third-party licenses |

---

## License and fiscal sponsorship

Pinpoint 311 is licensed under the [MIT License](LICENSE).

Pinpoint 311 is fiscally sponsored by
[The Hack Foundation](https://hackclub.com/fiscal-sponsorship/) (d.b.a. Hack
Club), a 501(c)(3) public charity (EIN: 81-2908499). Donations made through
[Hack Club Bank](https://hcb.hackclub.com/pinpoint-311) are tax-deductible to the
extent permitted by law.
