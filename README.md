<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/pinpoint311_logo_dark_transparent.png">
    <img src="frontend/public/pinpoint311_logo_light.png" alt="Pinpoint 311" height="60">
  </picture>
</h1>

<p align="center"><strong>Open-source, self-hosted 311 for small and mid-size towns.</strong></p>

<p align="center">
  <a href="https://pinpoint311.org"><img src="https://img.shields.io/badge/Website-pinpoint311.org-6366f1.svg" alt="Website"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://hcb.hackclub.com/pinpoint-311"><img src="https://img.shields.io/badge/Fiscal%20Sponsor-Hack%20Club-ec3750.svg" alt="Fiscally Sponsored by Hack Club"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/build-publish.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/build-publish.yml/badge.svg" alt="Build status"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/accessibility.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/accessibility.yml/badge.svg" alt="Accessibility audit"></a>
</p>

<p align="center">
  <a href="https://demo.pinpoint311.org">Live demo</a> &middot;
  <a href="#try-it">Try it</a> &middot;
  <a href="#how-it-works">How it works</a> &middot;
  <a href="docs/API.md">API</a> &middot;
  <a href="#documentation">Docs</a>
</p>

Residents report non-emergency problems (a pothole, a broken streetlight, a
missed pickup) without creating an account. Staff triage, route and close them
from one dashboard, and administrators configure everything in the browser. The
town runs it on its own server and owns the database. MIT-licensed, no per-seat
fees, and it keeps working when any optional cloud service is off.

## At a glance

<table>
  <tr>
    <td width="33%" valign="top"><strong>No-account reporting</strong><br>Pick a category, drop a pin, add up to three photos, and track the report through a private link.</td>
    <td width="33%" valign="top"><strong>One staff queue</strong><br>List, map, and detail views, scoped to each staff member's departments.</td>
    <td width="33%" valign="top"><strong>Configured in the browser</strong><br>Branding, users, departments, categories, routing, and every provider credential.</td>
  </tr>
  <tr>
    <td valign="top"><strong>Privacy by default</strong><br>Resident contact details are encrypted at rest; faces and plates are blurred before a photo is stored.</td>
    <td valign="top"><strong>Optional AI, never in charge</strong><br>Suggests a priority and summary. It never routes, assigns, or closes a report.</td>
    <td valign="top"><strong>More than 100 languages</strong><br>Interface, categories, and resident text, under a daily and monthly translation budget.</td>
  </tr>
  <tr>
    <td valign="top"><strong>Connects to town systems</strong><br>Accela, Esri ArcGIS, Tyler, any Open311 endpoint, or a generic REST API.</td>
    <td valign="top"><strong>Records and audit</strong><br>Retention set by the clerk, legal holds, and hash-chained audit logs with an integrity check.</td>
    <td valign="top"><strong>Signed, approved upgrades</strong><br>Signed images pinned by digest, upgraded from the console with a second admin's approval.</td>
  </tr>
</table>

## Screenshots

From the public pages of the [generic demo](https://demo.pinpoint311.org). Street
addresses in the tracker are blurred.

<table>
  <tr>
    <td width="50%"><img src="docs/images/resident-home.png" alt="Resident portal home page: a 'How can we help?' heading, a service search box, and a grid of eight category cards such as Pothole, Street Light, and Trash / Litter, under a non-emergency banner that says to call 911 for emergencies."></td>
    <td width="50%"><img src="docs/images/report-form.png" alt="Report form for the Pothole category: a description box, an address search field, and a satellite map with the township boundary outlined where the resident drops a pin."></td>
  </tr>
  <tr>
    <td align="center"><em>Residents start by choosing a category.</em></td>
    <td align="center"><em>The report form: describe, locate, attach photos.</em></td>
  </tr>
  <tr>
    <td><img src="docs/images/public-map.png" alt="Community Requests Map: a satellite map of the township with clustered request markers, beside a filter panel listing 69 plotted requests and checkboxes for Open, In Progress, and Closed."></td>
    <td><img src="docs/images/request-tracker.png" alt="Track Requests page: a search box, status filter buttons, counts of 62 open, 6 in progress, and 4 resolved requests, and request cards showing category, request ID, status badge, description, and date, with addresses blurred."></td>
  </tr>
  <tr>
    <td align="center"><em>The public map, with personal details removed.</em></td>
    <td align="center"><em>Anyone can follow the status of community reports.</em></td>
  </tr>
</table>

<details>
<summary>Mobile view</summary>

<p align="center"><img src="docs/images/resident-home-mobile.png" width="300" alt="Resident portal home page on a phone-width screen: the non-emergency banner, a language selector, the 'How can we help?' heading, a service search box, and category cards stacked in one column."></p>

</details>

## Try it

On a Linux host with Docker Engine and the Compose plugin:

```bash
git clone https://github.com/Pinpoint-311/Pinpoint-311.git
cd Pinpoint-311
cp .env.example .env    # then set DB_PASSWORD, SECRET_KEY, and INITIAL_ADMIN_PASSWORD
scripts/build-release.sh --latest   # or use the published images, see Quick start
docker compose up -d
docker compose logs -f backend
```

Then open `https://<your DOMAIN>` (or `https://localhost`) and choose
**Staff Login > Enter Admin Console**. Read the [Quick start](#quick-start)
before going live.

## Who it's for

| Role | What they get | Where to read |
| --- | --- | --- |
| Resident | Report without an account, follow a private status link, browse the public map | [Features](docs/FEATURES.md#resident-portal) |
| Staff | One queue, triage panel, notes, assignment, printable work orders | [Features](docs/FEATURES.md#staff-dashboard) |
| Administrator | Branding, users, departments, categories, routing, retention, and providers in the browser | [Features](docs/FEATURES.md#admin-console), [Configuration](docs/CONFIGURATION.md) |
| Researcher | An optional Research Suite the town can switch on: request volume, response times and geographic patterns, with CSV and GeoJSON exports that leave out free text and direct identifiers | [Features](docs/FEATURES.md#research-lab) |
| Town IT | A Docker Compose stack, one public listener, encrypted backups, signed upgrades only when you approve them | [Quick start](#quick-start), [Security model](#security-model), [Operations](docs/OPERATIONS.md) |
| Developer | FastAPI and React code, an Open311 API, pytest and Vitest suites | [How it works](#how-it-works), [API](docs/API.md), [Development](docs/DEVELOPMENT.md) |

## How it works

**System architecture.** Caddy is the only public listener; the host updater runs outside the stack and reaches the backend on loopback.

<details>
<summary>System architecture</summary>

```mermaid
flowchart LR
    updater["Host updater<br/>systemd, outside the stack"]
    subgraph stack["Docker Compose stack"]
        caddy["caddy<br/>TLS, headers, CSP<br/>only public listener, 80 and 443"]
        frontend["frontend<br/>nginx serving the React app"]
        subgraph be["backend"]
            api["FastAPI: REST API, Open311,<br/>migrations on start"]
            onnx["On-server ONNX models<br/>YOLOv9 plates, YuNet faces"]
        end
        worker["worker<br/>Celery worker and beat"]
        redis[("redis<br/>queue and caches")]
        db[("db<br/>PostgreSQL 15 and PostGIS")]
    end
    users(["Residents, staff, Open311 clients"]) --> caddy
    caddy -->|"/api/*"| api
    caddy -->|"everything else"| frontend
    api --- onnx
    api --> db
    api -->|"enqueue"| redis --> worker --> db
    updater -->|"loopback port, token"| api
    updater -->|"pull by digest, recreate"| stack
    api -.-> idp["Identity: Auth0, Entra ID, Okta, OIDC"] & kms["Secret store and KMS"] & vision["Cloud face detection"] & maps["Maps and geocoding"] & tr["Translation"]
    worker -.-> ai["AI: Vertex, Azure OpenAI, Bedrock"] & msg["Email and SMS"] & towns["Town systems"] & tr
```

</details>

**Request lifecycle.** The resident portal and an Open311 `POST` with an API key share one intake path (`backend/app/api/open311.py`).

<details>
<summary>Request lifecycle</summary>

```mermaid
flowchart TD
    portal["Resident portal"] & o311["Open311 POST with api_key"] --> code
    code{"Active service code?"} -->|"no"| refused["Refused with a reason to fix"]
    code --> loc{"Category location rule:<br/>required, optional or hidden"}
    loc -->|"required and missing"| refused
    loc --> text{"Text moderation"}
    text -->|"explicit"| refused
    text --> photo["Photo screening and redaction<br/>cloud faces, YOLO plates, YuNet fallback"]
    photo -->|"explicit image"| refused
    photo -.->|"cannot be checked"| held["Photo withheld for staff review"]
    photo --> road{"Third-party road at the pin?"}
    road -->|"yes"| redirect["Redirected to the responsible agency"]
    road --> route["Route to a department"]
    route --> save["Saved with a parcel and zone snapshot"]
    save --> audit["Mild language flagged,<br/>entry in the hash-chained audit log"]
    audit --> triage["AI triage, if enabled"]
    triage -->|"when triage finishes"| push["Push to connected town systems"]
    audit -.->|"90 s safety net"| push
    audit --> confirm["Confirmation email or SMS,<br/>translated within the budget"]
    audit --> staff["Department notified,<br/>staff assign and set in progress"]
    staff --> closed["Closed: resolved, no action, or referred"]
    closed --> notify["Status email or SMS to the resident,<br/>mirrored to town systems"]
    save --> listed{"Unlisted, hidden category or archived?"}
    listed -->|"no"| public["Public map and Open311 GET"]
    listed -->|"yes"| private["Tracking link and staff only"]
```

</details>

**Photo privacy.** Faces and plates are blurred on the full-size photo before it is stored, and the pipeline fails closed ([details](docs/PHOTO_REDACTION_MODELS.md)).

<details>
<summary>Photo privacy pipeline</summary>

```mermaid
flowchart TD
    src["Photo, up to three per report"] --> cloud["Cloud provider: explicit-image check and faces<br/>Google Vision, Rekognition or Azure AI"]
    src --> plate["YOLOv9-s plate model<br/>ONNX, inside the backend"]
    cloud -->|"explicit"| refused["Report refused"]
    cloud -->|"provider down, failing or not configured"| yunet["YuNet face model on the server"]
    cloud --> blur["Blur faces and plates, strip EXIF and GPS"]
    yunet --> blur
    plate --> blur
    yunet -->|"off or failed"| held["Withheld for staff review"]
    plate -->|"model missing, error or timeout"| held
    blur -->|"blur failed"| held
    blur --> stored["Stored, no unblurred original kept"]
    held --> review["Staff release or discard, audited"]
```

</details>

**Town-system sync.** Pushes and pulls run in the worker; a failed sync goes to a backlog and is retried ([details](docs/INTEGRATIONS.md)).

<details>
<summary>Town-system sync</summary>

```mermaid
flowchart LR
    subgraph pp["Pinpoint 311"]
        create["New report"]
        status["Status change"]
        comment["Public comment"]
        prio["Priority change"]
        backlog[("Failed syncs backlog")]
    end
    town["Town system<br/>Accela, ArcGIS, Tyler, Open311, REST"]
    create -->|"push after triage"| town
    status & comment -->|"push"| town
    prio -->|"push, where supported"| town
    town -->|"pull every 15 min: status,<br/>comments, work-order fields"| pp
    town -->|"inbound webhook"| pp
    create & status & comment & prio -.->|"on failure"| backlog
    backlog -.->|"retry every 10 min"| town
```

</details>

**Secure upgrades.** Admins request and approve in the console; only the host updater touches Docker ([details](docs/OPERATIONS.md#upgrades)).

<details>
<summary>Secure upgrades</summary>

```mermaid
flowchart TD
    req["Admin requests a signed, schema-compatible release"] --> two{"Two-person approval on?"}
    two -->|"yes"| second["A second admin approves"]
    two -->|"no"| claim
    second --> claim["Host updater claims it on its next poll"]
    claim --> pre{"Preflight: cosign signature,<br/>schema window, disk"}
    pre -->|"fails"| stop["Refused, nothing changed"]
    pre --> backup{"Verified backup:<br/>restored to scratch and compared"}
    backup -->|"fails"| stop
    backup --> pull["Pull both images by digest"]
    pull --> migrate{"Migrate in a one-off container"}
    migrate -->|"destructive"| hold["On hold for approval,<br/>old version serving"]
    migrate --> recreate["Recreate backend, worker, frontend"]
    recreate --> health{"Health check"}
    health -->|"healthy"| commit["Commit release.lock"]
    health -->|"unhealthy"| rollback["Roll back to previous digests"]
    claim -.- live["Each step reports live to the console.<br/>Heartbeats renew the lease, and silence fails the run."]
```

</details>

## Features and configuration

The portal, dashboard, console, Open311 API and Research Lab are described in
[docs/FEATURES.md](docs/FEATURES.md). Deployment values live in `.env`; the rest is
set in the Admin Console, and every optional service can stay off
([docs/CONFIGURATION.md](docs/CONFIGURATION.md)).

## Quick start

You need a Linux host with Docker and the Compose plugin (2 vCPUs, 4 GB RAM) and,
for HTTPS, a DNS name pointing at it with ports 80 and 443 open.

1. **Create `.env`** from `.env.example`: set `DB_PASSWORD`, `SECRET_KEY` (`openssl rand -hex 32`), `INITIAL_ADMIN_PASSWORD`, `DOMAIN`, and `TENANT_CADDY_PATH` ([all variables](docs/CONFIGURATION.md)).
2. **Edit the `Caddyfile`**: delete every site block after `{$DOMAIN:localhost}` except the `import /etc/caddy/tenants/*.caddy` line, and remove `import noindex` if the portal should be indexed by search engines.
3. **Start the stack** with `scripts/build-release.sh --latest && docker compose up -d`, or the published images (`-f docker-compose.yml -f docker-compose.prod.yml pull`, then `up -d`). In production, pin a signed release in `release.lock` ([docs/RELEASES.md](docs/RELEASES.md)).
4. **Sign in** with **Enter Admin Console** and `INITIAL_ADMIN_PASSWORD`. This bootstrap login stops working once an identity provider is saved.
5. **Finish setup** under **Admin Console > Setup & Integration**: secret store (encrypted database, Google Secret Manager, AWS Secrets Manager or Azure Key Vault), staff sign-in (Auth0, Microsoft Entra ID, Okta or generic OIDC), map provider and boundary, optional services, then users, departments and categories.

> [!IMPORTANT]
> `SECRET_KEY` signs staff sessions and derives the local encryption key. Keep a
> copy somewhere other than the server, and do not change it after launch.

## Security model

Caddy is the only public listener, and every other port is bound to `127.0.0.1`.
Staff sign in through your identity provider, and signing out revokes every
session the account holds. Resident PII is envelope-encrypted under a cloud KMS
or a local key. Audit logs are hash-chained, anchored nightly and verifiable
from the console. Images are signed in CI and pinned by digest. Details and a
diagram: [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md).

> [!WARNING]
> Redis has no password and must stay on loopback. Docker's iptables rules
> bypass host firewalls such as `ufw`, so never publish its port.

> [!WARNING]
> Never mount the Docker socket into the backend. It is equivalent to root on the host.

> [!CAUTION]
> If the cloud KMS key that wraps resident PII is destroyed, that data cannot be
> recovered from any backup. See [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md).

## Operations

**Upgrades.** Nothing updates itself, and the old in-app git-based version
switcher is gone. With the [host updater](updater/README.md) installed, an admin
requests an upgrade in **Version Control** and a second admin approves it. By
hand: Take a backup first, pin the release in `release.lock`, then run
`docker compose --env-file .env --env-file release.lock pull` and `up -d`. To
track the newest images instead, use `docker compose pull` with
`docker-compose.prod.yml`.

**Backups and health.** Daily GPG-encrypted backups go to S3-compatible storage
(keep the passphrase off the server; back up `uploads_data` separately), and a
15-minute health scan emails admins. More: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Integrations, development and accessibility

- **Town systems**: Accela, Esri ArcGIS, Tyler, generic Open311 and generic REST ([docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)).
- **API**: Open311 GeoReport v2 plus the staff API ([docs/API.md](docs/API.md)).
- **Development**: `docker-compose.dev.yml` runs from source with reload; pytest, Vitest and axe suites ([docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)).
- **Centralized hosting** (optional): a state, county or agency can run one instance per town with [Pinpoint-311/centralizedhosting](https://github.com/Pinpoint-311/centralizedhosting). Each town keeps its own database, key and secrets; this repository only carries the hooks, behind `MANAGED_MODE` (off by default). See [docs/VISION.md](docs/VISION.md).
- **Accessibility**: built toward WCAG 2.1 Level AA, with keyboard and screen-reader tests and an axe-core audit in CI. This is a design target, not an independent audit ([COMPLIANCE.md](COMPLIANCE.md#4-accessibility)).

## Reporting security vulnerabilities

> [!IMPORTANT]
> Do not open a public issue for a security vulnerability.

Use **Report a vulnerability** on the [Security tab](https://github.com/Pinpoint-311/Pinpoint-311/security).
We aim to acknowledge reports within 48 hours.

## Documentation

| Document | Contents |
| --- | --- |
| [FEATURES](docs/FEATURES.md), [CONFIGURATION](docs/CONFIGURATION.md) | What everything does, and how to set it |
| [OPERATIONS](docs/OPERATIONS.md), [RELEASES](docs/RELEASES.md), [updater](updater/README.md) | Upgrades, signed releases, the host updater, backups, health |
| [SECURITY_MODEL](docs/SECURITY_MODEL.md), [SECURITY_PLAN](docs/SECURITY_PLAN.md), [PRIVACY_ASSESSMENT](docs/PRIVACY_ASSESSMENT.md), [COMPLIANCE](COMPLIANCE.md) | Security and privacy |
| [PHOTO_REDACTION_MODELS](docs/PHOTO_REDACTION_MODELS.md) | Plate and face models, install, licenses |
| [API](docs/API.md), [INTEGRATIONS](docs/INTEGRATIONS.md), [DEVELOPMENT](docs/DEVELOPMENT.md) | For integrators and contributors |
| [DISASTER_RECOVERY](docs/DISASTER_RECOVERY.md), [SENTRY_SETUP](docs/SENTRY_SETUP.md) | Restore, key loss, crash reporting |
| [COST](COST.md), [deploy/templates](deploy/templates/README.md), [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md) | Costs, cloud templates, licenses |

## Sustainability and continuity

A town keeps control of its deployment. The full source is MIT-licensed, so it
can be run, modified or forked independently; the data stays in the town's own
PostgreSQL database; updates are applied only when the operator chooses; and a
standalone instance never needs the centralized-hosting control plane.

## License and fiscal sponsorship

Pinpoint 311 is licensed under the [MIT License](LICENSE).

Pinpoint 311 is fiscally sponsored by
[The Hack Foundation](https://hackclub.com/fiscal-sponsorship/) (d.b.a. Hack
Club), a 501(c)(3) public charity (EIN: 81-2908499). Donations made through
[Hack Club Bank](https://hcb.hackclub.com/pinpoint-311) are tax-deductible to the
extent permitted by law.

Pinpoint 311 is also organized as Pinpoint 311 LLC.
