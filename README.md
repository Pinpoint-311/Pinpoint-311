# Pinpoint 311 — Municipal Service Request Platform

<p align="center">
  <img src="frontend/public/pinpoint311_logo_light.png" alt="Pinpoint 311" height="60">
</p>
<p align="center">
  <a href="https://pinpoint311.org"><img src="https://img.shields.io/badge/Website-pinpoint311.org-6366f1.svg" alt="Website"></a>
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT">
  <a href="https://hcb.hackclub.com/pinpoint-311"><img src="https://img.shields.io/badge/Fiscal%20Sponsor-Hack%20Club-ec3750.svg" alt="Fiscally Sponsored by Hack Club"></a>
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg" alt="React 18">
  <img src="https://img.shields.io/badge/FastAPI-0.109-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-15-336791.svg" alt="PostgreSQL 15">
  <img src="https://img.shields.io/badge/AI-pluggable-8E24AA.svg" alt="Pluggable AI providers">
  <img src="https://img.shields.io/badge/Geo-PostGIS-336791.svg" alt="PostGIS">
</p>

<p align="center">
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/build-publish.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/build-publish.yml/badge.svg" alt="Build Status"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/codeql.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/security-scan.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/security-scan.yml/badge.svg" alt="Security Scan"></a>
  <a href="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/accessibility.yml"><img src="https://github.com/Pinpoint-311/Pinpoint-311/actions/workflows/accessibility.yml/badge.svg" alt="Accessibility"></a>
</p>

## Introduction

Most towns can't justify a five-figure annual contract for a modern 311 system — so they're stuck with paper forms, a clunky web form, or nothing at all. Pinpoint 311 is the alternative: complete, self-hosted 311 software that a small or mid-size municipality can actually run, own, and afford.

Residents report an issue in about a minute — no account, in their own language, with a photo and a map pin. Staff triage, route, and resolve everything from one dashboard, with optional AI assistance. Admins configure the whole system from the browser. And because it's self-hosted and MIT-licensed, the town owns its data outright — no vendor lock-in, no per-request bill.

Every advanced capability — AI assistance, translation, encryption, notifications, content moderation — is optional and works with the cloud your town already uses. Turn on what you need; everything else stays out of the way, and the platform keeps running without it.

This is enterprise-grade civic software for the towns that got left behind.

---

## Table of Contents

- [Why Pinpoint?](#why-pinpoint)
- [Who It's For](#who-its-for)
- [Core Features Overview](#core-features-overview)
- [Resident Portal Features](#resident-portal-features)
- [Staff Dashboard Features](#staff-dashboard-features)
- [Admin Console Features](#admin-console-features)
- [Research Suite](#research-suite-university-lab-integration)
- [Technical Architecture](#technical-architecture)
- [Deployment & Setup](#deployment--setup)
- [Centralized Hosting](#centralized-hosting-managed-mode)
- [Security & Governance](#security--governance)
- [License](#license)

---

## Why Pinpoint?

Small towns deserve the same tools big cities pay a fortune for. Here's what changes when you switch from a paper form or a basic web form to Pinpoint 311:

| | The old way | With Pinpoint 311 |
| :--- | :--- | :--- |
| Cost | Free but limited, or a yearly hosted contract | Free and open source, self-hosted |
| Your data | Locked in a vendor's cloud | Owned by the town, on your infrastructure |
| Reporting | Type an address into a form | GPS pin, map, photos, and asset selection |
| Language | English only | 100+ languages, including notifications |
| Triage | Sort every ticket by hand | Rules-based routing, plus optional AI summaries, priority suggestions, and photo analysis |
| Tracking | Email, if anything | Live status by magic link, SMS, and email |
| Privacy | Little to none | Field-level PII encryption and redaction |
| Research | Not available | 60+ privacy-preserved data fields, included |
| Branding | Generic | Full white-label — your name, colors, and logo |

The town owns the deployment and the data outright: no per-seat pricing, no per-request billing, and no vendor lock-in.

---

## Who It's For

One platform, four purpose-built experiences.

<table>
<tr>
<td width="25%" valign="top">

### 🏠 For Residents
Report an issue in about a minute.

- No account, ever
- 100+ languages
- Photo + map pin
- Track by magic link

<a href="#resident-portal-features">Resident features →</a>

</td>
<td width="25%" valign="top">

### 🧰 For Staff
Everything in one place.

- One dashboard for the queue
- AI summaries & priority (optional)
- Routing & internal notes
- Analytics assistant

<a href="#staff-dashboard-features">Staff features →</a>

</td>
<td width="25%" valign="top">

### ⚙️ For Admins
Run it from the browser.

- Services & routing rules
- Full white-label branding
- Providers & integrations
- Users, roles & backups

<a href="#admin-console-features">Admin features →</a>

</td>
<td width="25%" valign="top">

### 🔬 For Researchers
Study your town's data.

- 60+ analysis fields
- Privacy-preserved
- CSV & GeoJSON export
- Census integration

<a href="#research-suite-university-lab-integration">Research suite →</a>

</td>
</tr>
</table>

<details>
<summary><b>System Architecture</b> (click to expand)</summary>

```mermaid
graph TB
    subgraph "Frontend"
        RP[Resident Portal]
        SP[Staff Dashboard]
        AC[Admin Console]
        RL[Research Lab]
    end

    subgraph "Backend Services"
        API[FastAPI Server]
        WK[Celery Worker + Beat]
        RD[(Redis Cache)]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL + PostGIS)]
    end

    subgraph "Infrastructure"
        CD[Caddy HTTPS]
        WT[Watchtower auto-update, optional]
    end

    subgraph "Pluggable Providers - bring your own cloud"
        AI[AI summaries & vision]
        TR[Translation]
        SEC[Secrets + PII encryption]
        MSG[Email + SMS]
        MOD[Content moderation]
    end

    subgraph "Integrations"
        GM[Maps]
        IDP[Staff sign-in / SSO]
        GT[Town-system connectors]
    end

    RP --> CD
    SP --> CD
    AC --> CD
    RL --> CD
    CD --> API
    CD --> |static| RP

    API --> PG
    API --> RD
    API --> WK

    WK --> AI
    WK --> TR
    WK --> MSG

    API --> SEC
    API --> MOD
    API --> GM
    API --> IDP
    WK --> GT
```

</details>

<details>
<summary><b>Request Lifecycle</b> (click to expand)</summary>

```mermaid
flowchart LR
    A[Resident submits] --> B{Within boundary?}
    B -->|No| C[Rejected]
    B -->|Yes| M{Content check}
    M -->|Explicit| C2[Blocked]
    M -->|OK| D[Created]

    D --> E[AI analysis, if enabled]
    E --> F[Confirmation email]

    F --> G[Staff reviews]
    G --> H{Action?}

    H -->|Assign| I[In Progress]
    H -->|Resolve| J[Resolved]
    H -->|Transfer| K[Third party]

    I --> J
    J --> L[Closure email]
```

</details>

<details>
<summary><b>Security Stack</b> (click to expand)</summary>

```mermaid
graph LR
    subgraph "Identity"
        IDP[Auth0 / Entra / Okta / OIDC]
        MFA[MFA / Passkeys]
    end

    subgraph "Secrets and Encryption"
        SEC[Secret Manager / Key Vault / Secrets Manager]
        KMS[Envelope KMS for PII]
    end

    subgraph "Infrastructure"
        CD[Caddy HTTPS]
        AL[Hash-chained audit log]
    end

    IDP --> MFA
    SEC --> KMS
    CD --> AL
```

</details>

## Core Features Overview

### 🎨 Built for people, not paperwork
- Responsive web app for desktop and mobile browsers.
- 100+ language support via the configured translation provider, with caching. Coverage includes UI strings, service categories, status labels, filters, priority levels, and resident-submitted content. Confirmation emails and SMS are sent in the resident's selected language.
- No-login submission for residents, with email magic-link tracking.

### 🤖 Optional intelligence
- PII redaction: names, phones, and emails are stripped from public request logs.
- Photo analysis: when AI is enabled, a vision model categorizes uploaded photos (for example, distinguishing a pothole from water damage). The AI provider is your choice and configured in the browser.
- Multilingual analysis: non-English descriptions are translated to English before analysis so staff can read every submission.
- Priority scoring (human-in-the-loop): the AI suggests a 1–10 urgency score, but it is never applied automatically. Staff explicitly accept or override it, and the decision is recorded in the audit log.

### 🗺️ Location-aware
- Asset selection: when map layers are configured, residents can select the specific asset (streetlight, hydrant, park zone) a report relates to.
- Boundary enforcement: requests are validated against uploaded GeoJSON boundaries with point-in-polygon checks.
- Clustering: request markers group on the map; backend hotspot detection uses PostGIS `ST_ClusterDBSCAN`.

### ☁️ Runs on your terms
- Bring your own cloud: pick one cloud environment and it configures AI, translation, secret storage, PII encryption, email, and text messaging together — or set each one independently. Provider settings live in the Admin Console; no config files to edit.
- Secrets stay in your vault: when an external secret store is configured, credentials are written there and the database keeps only a reference — the raw key never sits in the app's database.
- Self-updating model list: the AI model picker refreshes the available models directly from your provider, so a retired model never silently breaks triage.
- Nothing is mandatory: every advanced provider is optional. If one is unconfigured or unreachable, that feature is skipped with a warning in the Admin Console and the rest of the platform keeps running. Core data safety (the database, PII encryption when required) fails loudly instead.

### 🛡️ Safe by default
- Content moderation on every public submission: descriptions and comments are screened as they come in — explicit or abusive content is blocked at submission, while ordinary (even frustrated) reports go through and are flagged for staff. Photo screening runs through the configured AI or cloud moderation service.
- Tamper-evident audit log: every action is recorded in a hash-chained log, anchored daily so history can't be quietly rewritten.
- State-aware records retention: automatic retention and legal-hold handling mapped to each state's public-records law (OPRA, FOIA, and equivalents).

### 🔌 Connects to what your town already runs (in active development)
Two-way connectors let requests, status, comments, and photos flow between Pinpoint and the systems a town already uses. This is an area under active development — coverage and vendor certification are expanding.
- Purpose-built connectors for permitting and 311 systems that publish an open or documented API, plus support for the Open311 standard.
- A single configurable connector for any other vendor that exposes a REST API — you provide the endpoint and key. It is clearly labeled as generic (not certified against a specific vendor) and is verified with a built-in connection check and a test report before go-live.
- Building or hardening a connector for your vendor is ongoing work; if you run a system not yet covered, the generic connector is the starting point.

---

## Resident Portal Features

The Resident Portal is the public-facing submission and tracking interface.

### 1. Service Discovery
- **Visual Grid**: Services are displayed with clear, consistent iconography (Lucide React) for instant recognition.
- **Service Categories**: Browsable catalog of all available township services.

### 2. Intelligent Location Picker
- **Interactive Map**: Google Maps integration with drag-to-set pin functionality.
- **Address Autocomplete**: Type-ahead search for local addresses.
- **Jurisdiction Boundaries**: System-level polygons (GeoJSON) define the valid service area. PINS dropped outside are auto-rejected.
- **Asset Selection**: When map layers are configured, residents can click on infrastructure assets displayed on the map (e.g., specific park zones, hydrants) and select the one related to their report.

### 3. Advanced Routing Logic
- **Road-Based Routing**: Configurable rules for state/county roads.
    - *Example*: Potholes on "Route 1" are automatically blocked with a custom message: "This road is maintained by the State DOT. Please call 555-0199."
- **Third-Party Hand-off**: Services managed by private contractors (e.g., Waste Management) show specific contact info instead of a generic form.

### 4. Submission & Tracking
- **Multi-Photo Upload**: Supports up to 3 high-res images with client-side compression.
- **Magic Link Tracking**: Users receive a unique, hash-based tracking link (e.g., `/track/req-123`) to view live status updates without creating an account.
- **Status Timeline**: clean visualization of the request journey from "Received" → "In Progress" → "Resolved" → "Closed".
- **Public Request Map**: Interactive map allowing residents to view all open and resolved requests. Features robust filtering by:
    - **Department** (Police, Public Works, etc.)
    - **Status** (Open, Closed, In Progress)
    - **Date Range**
    - **Service Type**

---

## Staff Dashboard Features

The Staff Dashboard is the operational interface for reviewing and resolving requests, protected by JWT authentication.

### 1. Unified Workspace
- **Live Feed**: Auto-refreshes every 30s; identifying "NEW" requests with badging.
- **Split-Pane View**: Independent scrolling for the request list and details panel.
- **Interactive Map**: Features "Satellite View" for precise location verification. Includes comprehensive filters for:
    - **Priority Level** (Critical, High, Normal)
    - **Department & Assigned Staff**
    - **Status & Date Range**
    - **Service Category**

### 2. Collaboration Tools
- **Internal Comments**: Private staff-only notes for coordination.
- **External Updates**: Public comments visible to residents via the tracker.
- **Staff Preferences**: Each staff member can toggle their own SMS/Email notifications.
- **Audit log**: Tamper-evident, hash-chained history of every action (status change, assignment, comment). The chain is anchored daily so tampering can be detected.

### 3. Request Management
- **Smart Assignment**: Auto-route to specific departments or keep in a general queue.
- **Completion Types**: Close requests as **Resolved** (with photo proof), **No Action Needed** (invalid), or **Transferred** (third-party).
- **Priority Override**: Staff set or change a request's priority at any time; nothing sets it automatically.
- **Asset History**: When viewing a request attached to a physical asset (e.g., Hydrant #404), automatically shows all past history for that specific asset.
- **Status Workflow**:
    - **Open**: New request.
    - **In Progress**: Staff acknowledged and working.
    - **Resolved**: Work complete.
    - **Closed**: Final state (includes optional "Completion Photo" proof).

### 4. Triage Panel
This panel is decision *support*, not automation. Routing and assignment are handled by the rules you configure (see Advanced Routing and Smart Assignment), not by AI. Most of the panel — history, proximity, weather, similar reports — is pulled deterministically from your own data and works whether or not AI is enabled. When AI is enabled, it synthesizes that same data into a plain-language summary and a suggested priority; it does not route, assign, close, or decide anything on its own, and its suggestions only take effect when a staff member accepts them.

- **Safety flags**: highlights potential liabilities (for example, a downed power line) from the AI assessment.
- **Proximity analysis**: checks whether the issue is near critical infrastructure (schools, hospitals, fire stations) via PostGIS, with a Nominatim (OpenStreetMap) fallback for unmapped areas. Computed without AI.
- **Sentiment**: estimates the tone of the description (neutral, frustrated, urgent) when AI is on.
- **Weather context**: fetches current weather for the location to help assess hazards. Computed without AI.
- **Pluggable AI**: the summary and photo assessment run on whichever AI provider you configure. The model list refreshes live from the provider, and if a model is retired the picker flags it. If AI is off or unreachable, requests still submit and the panel shows the computed context above.
- **Similar request detection**: surfaces nearby requests within ~50m and a recent time window for staff awareness. Requests are never flagged as duplicates or deleted automatically; any action is left to staff.
- **Human-in-the-loop priority**: the AI produces a priority score, but it is **never written to the request's priority**. It is kept as a suggestion in the analysis data and shown with an "Accept AI Priority" action; the request's priority only changes when a staff member accepts it, and that acceptance is recorded in the audit log.
- **PostGIS Geospatial Analytics**:
    - **Hotspot Analysis**: Automatically clusters requests to identify problem areas (e.g., "Pothole Clusters" on specific roads).
    - **User Bias Detection**: Flags suspicious activity using spatial statistics (e.g., single user spamming requests in a 10m radius).
    - **Jurisdiction Verification**: Real-time point-in-polygon checks against township boundaries.

### 5. Analytics Assistant
A conversational interface, running on the configured AI provider, that lets staff ask questions about their data in natural language. It cross-references system data with the Research Suite's aggregated metrics.

- **Natural-language queries**: ask questions such as "What's our average triage time?" or "Are there gaps in our response times by area?" and get answers with specific numbers.
- **Research-Grade Context**: The AI has access to aggregated metrics from the Research Suite:

| Data Category | Metrics Available |
|---|---|
| **Social Equity** | Social Vulnerability Index (SVI), income quintile distribution, housing tenure, population density |
| **Resident Sentiment** | Average sentiment score, frustration rate, repeat report rate, prior report references |
| **Bureaucratic Friction** | Average triage time, reassignment count, off-hours submission rate, escalation rate |
| **Infrastructure** | Category breakdown (roads/pavement, lighting, stormwater, etc.) |

- **Cross-Referencing**: Connects patterns across categories—e.g., correlating response times with social vulnerability, or sentiment with seasonal trends.
- **Formatted Responses**: Outputs structured markdown with section headers, bold metrics, comparison tables, and "Key Takeaway" summaries.
- **Conversation Memory**: Maintains multi-turn context so staff can drill into follow-up questions.
- **Privacy-First**: Never exposes resident PII—all data is aggregated and sanitized before reaching the AI.
- **Clear Conversation**: One-click reset to start fresh analysis sessions.

### 6. Manual Intake (Call-Takers & Walk-Ins)
Not every resident submits online. Staff can log a request on someone's behalf — a phone call, a walk-in, or a forwarded email — from the dashboard.

- **Same pipeline**: manually-logged requests run through the exact same routing, notifications, and triage as resident submissions, so nothing is second-class.
- **No fake data**: optional fields left blank (for example, a caller who didn't leave an email) simply skip the steps that need them — a placeholder address is never invented, and no confirmation is sent to an address that doesn't exist.
- **Channel captured**: the intake channel (phone, walk-in, email) is recorded for reporting.

---

## Admin Console Features

Configuration for the municipality's deployment, without editing code.

- **Custom Icons**: Select from a library of 100+ icons.
- **Routing Rules**: Assign services to specific departments (e.g., "Potholes" → "DPW").
- **SLA Definitions**: Set expected response times (e.g., "24 hours" for urgent issues).

### 1. Service Configuration
- **Granular Routing**: Configure each service category (e.g., "Pothole") to:
    - **Township Handled**: Route to internal Public Works department.
    - **Third-Party Handoff**: Direct residents to external agencies (e.g., "This road is state-maintained, please call DOT at...").
    - **Road-Based Logic**: Automatically split jurisdiction based on specific street names (e.g., "Main St" goes to County, "Elm St" stays local).
- **Custom Questions**: specific follow-up questions (e.g., "Is the dog aggressive?") for each service category to gather precise details.

### 2. System Management
- **System Updates**: One-click "Pull Updates" to fetch the latest code from GitHub and rebuild containers.
- **Custom Map Layers**: Upload **GeoJSON** files to visualize township assets (Parks, Storm Drains, Zoning Districts) directly on the staff map.
- **Domain Configuration**: Automatic HTTPS provisioning via Caddy (Let's Encrypt) for custom domains.
- **Service providers**: select and configure the AI, translation, and identity providers from the Admin Console. One "cloud environment" choice can point AI, translation, secret storage, PII encryption, email, and SMS at the same cloud, or you can set each independently. Credentials are written to the configured secret store; when an external vault is used, the database holds only a reference, not the secret.
- **Key management**: store the Google Maps key and other service keys in the configured secret store, with an encrypted database fallback.
- **Feature modules**: toggle features such as AI analysis or SMS alerts globally from the modules panel. Disabled or unconfigured providers are skipped; the rest of the system continues to run.
- **Database Maintenance**: Tools to seed default data or flush test records.

### 3. Legal Documents & Compliance
Fully customizable legal pages with sensible defaults based on municipal 311 best practices:

- **Privacy Policy**: Customizable Markdown content explaining data collection, usage, and retention. Default covers:
  - What information is collected (email required, optional phone)
  - How data is used (service request processing and communication)
  - Data sharing with relevant departments and third parties
  - Resident rights (access, correction, deletion)
  
- **Terms of Service**: Customizable Markdown with prominent non-emergency disclaimer. Default emphasizes:
  - Non-emergency use only (911 for emergencies)
  - Acceptable use policy
  - Response time expectations
  - Liability limitations
  
- **Accessibility Statement**: Customizable Markdown for the town's accessibility commitments. Default includes:
  - A WCAG 2.1 Level AA goal
  - A Section 508 reference
  - Alternative submission methods (phone, email, in-person)
  - Contact information for accessibility concerns

All legal pages are editable via **Admin Console → Branding → Legal Documents**.

---

## Non-Emergency Disclaimer

Residents are informed that 311 is for non-emergency municipal services only.

### One-time acknowledgment modal
- Users must acknowledge before accessing the portal.
- Persisted in `localStorage`, so it shows once per browser.

### Persistent warning banner
- A banner at the top of the resident portal reads: "Non-Emergency Only — For police, fire, or medical emergencies, call 911."

### Legal Audit Logging
Every acknowledgment is logged to the `disclaimer_acknowledgments` table:

| Field | Description |
|-------|-------------|
| `session_id` | Unique browser session identifier |
| `ip_address` | Client IP (supports IPv4/IPv6, handles proxies) |
| `user_agent` | Browser/device information |
| `acknowledged_at` | Timestamp with timezone |
| `disclaimer_version` | Version string for tracking policy updates |

This creates a complete paper trail for legal protection if any user claims they weren't aware of the non-emergency nature of the service.

---

## Research Suite (University Lab Integration)

A privacy-preserving analytics layer that serves two audiences at once.

**For the town's own staff and leadership**, it turns day-to-day requests into a planning tool — the goal is to move from reactive repair (fixing what breaks after residents report it) toward proactive maintenance. Hotspot clustering surfaces the streets and assets that generate repeat reports, so a department can schedule work before the next failure; trends by category, season, and area inform budgets and staffing; and asset-linked history shows which infrastructure is nearing the end of its life.

**For external researchers** (university labs, policy groups), it exports 60+ privacy-preserved fields for study of municipal operations, infrastructure, equity, and civic engagement.

The same sanitized dataset backs both, and it also feeds the Staff Dashboard's analytics assistant. Exports 60+ fields computed from the underlying data.

### Access Control
- **Researcher Role**: Dedicated user role with read-only access to sanitized data
- **Admin Toggle**: Enable/disable via Admin Console → Modules → Research Portal
- **Audit Logging**: All data access is logged for governance compliance

### Data Exports
Two export formats optimized for different research toolchains:

| Format | Use Case | Tools |
|--------|----------|-------|
| **CSV** | Statistical analysis | Python (pandas), R, SPSS, Excel |
| **GeoJSON** | Spatial analysis | QGIS, ArcGIS, GeoPandas, Mapbox |

### Privacy Preservation
All exports are designed to protect resident privacy while enabling meaningful research:

- **PII Redaction**: Phone numbers, emails, and names are masked in descriptions
- **Address Anonymization**: House numbers removed, street names preserved (e.g., "123 Main St" → "Main Street (Block)")
- **Location Fuzzing**: Coordinates snapped to ~100ft grid (default) or exact (admin only)
- **Zone IDs**: Anonymous geographic zones (~0.5 mile cells) for clustering without revealing exact locations

---

### Research Packs (5 Specialized Domains)

#### Social Equity Pack (Sociologists)
Census data integration for equity research.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `census_tract_geoid` | string | 11-digit FIPS code for Census joins | US Census Geocoder API |
| `social_vulnerability_index` | float (0-1) | CDC SVI (0=lowest, 1=highest) | Derived from GEOID |
| `housing_tenure_renter_pct` | float (0-1) | Renter percentage in zone | Derived from GEOID |
| `income_quintile` | int (1-5) | Anonymized income quintile | Zone-based proxy |
| `population_density` | string | low/medium/high category | Zone-based proxy |

**Suggested Analyses**: Census ACS demographic correlation, SVI vs response time regression, renter vs owner reporting rates

---

#### 🔵 Environmental Context Pack (Urban Planners)
Real historical weather data and infrastructure lifecycle analysis.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `weather_precip_24h_mm` | float | Precipitation 24h before report | Open-Meteo Archive API |
| `weather_temp_max_c` | float | Max temperature on report day | Open-Meteo Archive API |
| `weather_temp_min_c` | float | Min temperature on report day | Open-Meteo Archive API |
| `weather_code` | int | WMO weather code (61=rain, 71=snow) | Open-Meteo Archive API |
| `nearby_asset_age_years` | float | Age of matched infrastructure | Asset properties |
| `matched_asset_attributes` | JSON | Full asset properties (pressure_psi, acres, bulb type) | GeoJSON layer |
| `season` | string | winter/spring/summer/fall | Calculated |

**Suggested Analyses**: Freeze-thaw pothole correlation, asset survival analysis, precipitation-drainage linkage

---

#### 🩷 Sentiment & Trust Pack (Political Scientists)
NLP-derived indicators of civic trust and satisfaction.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `sentiment_score` | float (-1 to +1) | NLP sentiment (-1=angry, +1=grateful) | Word-based NLP |
| `is_repeat_report` | boolean | Text indicates prior report of same issue | Regex detection |
| `prior_report_mentioned` | boolean | References ticket/case number | Regex detection |
| `frustration_expressed` | boolean | Trust erosion indicators present | Regex detection |

**Suggested Analyses**: Sentiment vs income quintile, repeat report resolution rates, trust erosion over time

---

#### 🟠 Bureaucratic Friction Pack (Public Administration)
Quantified measures of administrative efficiency and government responsiveness.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `time_to_triage_hours` | float | Hours from submission to first "In Progress" | Audit logs |
| `reassignment_count` | int | Times request bounced between departments | Audit logs |
| `off_hours_submission` | boolean | Submitted before 6am or after 10pm | Timestamp |
| `escalation_occurred` | boolean | Priority manually increased by staff | Audit logs |
| `total_hours_to_resolve` | float | Total clock hours to closure | Calculated |
| `business_hours_to_resolve` | float | Business hours only (Mon-Fri 8am-5pm) | Calculated |
| `days_to_first_update` | float | Days until first staff action | Calculated |
| `status_change_count` | int | Number of status changes | Audit logs |

**Suggested Analyses**: Triage time vs resolution outcome, department routing efficiency, off-hours urgent patterns

---

#### 🟢 AI/ML Research Pack (Data Scientists)
Training data for AI systems and human-AI alignment studies.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `ai_flagged` | boolean | AI flagged for staff review | AI provider |
| `ai_flag_reason` | string | Reason for flag (safety, urgent) | AI provider |
| `ai_priority_score` | float (1-10) | AI-generated priority | AI provider |
| `ai_classification` | string | AI-assigned category | AI provider |
| `ai_summary_sanitized` | string | AI summary (PII redacted) | AI provider |
| `ai_analyzed` | boolean | Whether AI processed this request | System |
| `ai_vs_manual_priority_diff` | float | manual_priority - ai_priority | Calculated |

**Suggested Analyses**: AI-human priority alignment, flagging accuracy, classification accuracy studies

---

### Real-Time Data Sources
All research fields are computed on-the-fly using real APIs:

| Source | Fields | Notes |
|--------|--------|-------|
| **US Census Bureau Geocoder** | census_tract_geoid | Free, no API key required |
| **Open-Meteo Archive API** | weather_* fields | Free historical weather data |
| **NLP Analysis** | sentiment_score, trust indicators | Word-based sentiment analysis |
| **Audit Logs** | bureaucratic friction fields | Real system data |
| **AI provider** | ai_* fields | If AI analysis is enabled |

### API Endpoints
| Endpoint | Description |
|----------|-------------|
| `GET /api/research/status` | Check if Research Suite is enabled |
| `GET /api/research/analytics` | Aggregate statistics and distributions |
| `GET /api/research/export/csv` | Download sanitized CSV with all 60+ fields |
| `GET /api/research/export/geojson` | Download GeoJSON for GIS analysis |
| `GET /api/research/data-dictionary` | Complete field documentation for academic papers |
| `GET /api/research/code-snippets` | Python & R code examples |

---

## Technical Architecture

### Communication Engine
- **Branding Engine**: Automatically injects township logo, colors, and font settings into every email.
- **Text alerts**: sends status updates with request details (category, address) and a magic link for tracking.
- **Provider-agnostic**: works with common text-messaging services or a generic HTTP gateway; configured in the browser.
- **Completion Proof**: "Review & Close" workflow attaches the final resolution photo to the closing email sent to the resident.

### Standards Compliance
- **Open311 v2**: Compatible with the Open311 GeoReport v2 standard (JSON).
- **Interactive API Docs**: Available at `/api/docs` (Swagger UI) and `/api/redoc` (ReDoc).
- **Audit Trails**: Every action (submission, comment, status change) is logged for accountability.

#### Public Endpoints (No Authentication Required)

| Method | Endpoint | Description | Rate Limit |
|--------|----------|-------------|------------|
| `GET` | `/api/open311/v2/services.json` | List available service categories | Global |
| `POST` | `/api/open311/v2/requests.json` | Submit a new service request | **10/min per IP** |
| `GET` | `/api/open311/v2/public/requests` | List all requests (PII stripped, cached via Redis) | Global |
| `GET` | `/api/open311/v2/public/requests/{id}` | Get request detail (PII stripped) | Global |
| `GET` | `/api/open311/v2/public/requests/{id}/comments` | Get public comments on a request | Global |
| `POST` | `/api/open311/v2/public/requests/{id}/comments` | Add a public comment (anonymous) | **5/min per IP** |
| `GET` | `/api/open311/v2/public/requests/{id}/audit-log` | Status change history (staff names redacted) | Global |

#### Authenticated Endpoints (Staff/Admin Only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/open311/v2/requests.json` | List all requests with full PII |
| `GET` | `/api/open311/v2/requests/{id}.json` | Get full request detail with PII |
| `PUT` | `/api/open311/v2/requests/{id}/status` | Update status, assignment, or priority |
| `POST` | `/api/open311/v2/requests/manual` | Create request from phone/walk-in intake |
| `DELETE` | `/api/open311/v2/requests/{id}` | Soft-delete a request (requires justification) |
| `POST` | `/api/open311/v2/requests/{id}/restore` | Restore a soft-deleted request |
| `POST` | `/api/open311/v2/requests/{id}/accept-ai-priority` | Accept AI-suggested priority score |
| `GET` | `/api/open311/v2/requests/{id}/audit-log` | Full audit log with staff names |
| `GET` | `/api/open311/v2/requests/asset/{id}/related` | Find all requests linked to an asset |

#### API Security Notes

- **Public endpoints never expose**: staff usernames, resident PII (email, phone, name), or internal department IDs
- **Staff audit log entries** in public views show "Staff" instead of individual usernames
- **Legal hold** (`flagged` field) can only be toggled by admin-role users
- **Global rate limit**: 500 requests/minute per IP across all endpoints (via SlowAPI)
- **Authentication**: Staff endpoints require a valid JWT bearer token from the configured identity provider

### Tech Stack
| Component | Technology | Description |
|-----------|------------|-------------|
| **Frontend** | React 18 + TypeScript | Performant, type-safe UI built with Vite |
| **Styling** | Tailwind CSS + Framer Motion | Fluid animations and glassmorphism themes |
| **Backend** | FastAPI (Python 3.11) | High-performance async REST API |
| **Database** | PostgreSQL 15 + PostGIS | Relational data with advanced spatial queries |
| **Migrations** | Alembic | Version-controlled database schema changes |
| **Caching** | Redis | High-speed caching for public request feeds (60s TTL) |
| **AI** | Pluggable provider (configured in the browser) | Multimodal model for image and text analysis; optional |
| **Queue** | Celery + Redis | Background processing for emails and reports |
| **Reverse Proxy** | Caddy | Automatic HTTPS and SSL termination |

### 💾 Resource Footprint

The whole stack is light. Measured at idle on a small VM:

| Service | CPU | Memory |
|---------|-----|--------|
| PostgreSQL (db) | ~4% | 18 MB |
| Backend (FastAPI) | <1% | 23 MB |
| Worker (Celery) | <1% | 94 MB |
| Frontend (Nginx) | <1% | 3 MB |
| Caddy (HTTPS) | ~1% | 14 MB |
| Redis | <1% | 4 MB |
| **TOTAL** | **~6%** | **~160 MB** |

These are idle-baseline figures; actual usage varies with traffic and which optional providers are enabled. AI, translation, and moderation run in the provider's cloud, so they add little to the local footprint.

**Deployment cost:** runs comfortably on a small cloud VM (roughly 1 vCPU, 1 GB RAM), which is inexpensive on most providers. Larger towns may want more headroom.

### 🗄️ Database Migrations (Alembic)

Pinpoint 311 uses **Alembic** for database schema versioning:

```bash
# Inside the backend container
cd /app

# Create a new migration after model changes
alembic revision --autogenerate -m "Add new column to requests"

# Apply pending migrations
alembic upgrade head

# View current migration state
alembic current
```

**Configuration Notes:**
- PostGIS/Tiger geocoder tables are **excluded** from autogenerate to prevent false positives
- Migrations are stored in `backend/alembic/versions/`
- Use `alembic stamp head` to mark an existing database as up-to-date without running migrations

### 🔒 Security Standards

#### Security Layers
Each layer works with the provider your town chooses; where nothing external is configured, the platform falls back to encrypted database storage.

| Layer | Purpose | Options |
|-------|---------|---------|
| **Identity** | Staff SSO with MFA and passkeys | Auth0 by default; Microsoft Entra ID, Okta, or generic OIDC |
| **Secret storage** | API keys and connection credentials | Your cloud's secret store, with an encrypted database fallback |
| **PII encryption** | Resident PII at rest | Envelope encryption with your cloud's key service, or a local key |
| **Auto-update** | Optional container updates | Self-hosted, off by default |

#### Staff authentication
Staff sign in through your identity provider (Auth0 by default). Passwords are never stored by Pinpoint — authentication is delegated to the provider, which supports MFA, passkeys/WebAuthn, and social login.

#### Secrets and PII
Two tiers of protection:

| Secret type | Storage | Encryption |
|-------------|---------|------------|
| API keys and integration credentials | External secret store when configured; the database keeps only a reference | Provider-managed keys |
| Resident PII (email, phone, name) | Encrypted in the database | Envelope encryption; the data key is wrapped by your cloud's key service |
| Local development / no external vault | Encrypted database | Fernet (AES-128-CBC) |

When an external secret store is configured, integration and provider credentials are written there and the application database holds only a reference — the raw secret does not live in the app database. A small set of bootstrap keys needed to *reach* the secret store remain in the encrypted local table.

#### Cloud authentication
Cloud provider access uses credentials you enter during setup, encrypted at rest with `SECRET_KEY` in the `system_secrets` table and decrypted only at call time.
4. Decrypted at runtime when calling the configured cloud services

#### API & Infrastructure Security
- **Rate Limiting**: 500 requests/minute per IP (slowapi)
- **Security Headers**: X-Frame-Options, CSP, nosniff, XSS protection
- **RBAC**: Staff, Researcher, Admin roles with JWT authentication
- **Input Validation**: Pydantic schemas and parameterized queries via the SQLAlchemy ORM
- **Audit Logging**: Tamper-evident, hash-chained trail of request lifecycle events

For full security details, see [COMPLIANCE.md](./COMPLIANCE.md).

#### AI Provider Security
Data-residency, encryption, retention, and certification guarantees for AI depend on the provider you configure, not on Pinpoint. What Pinpoint controls:

| Feature | What Pinpoint does |
|---------|--------------------|
| Data sent to the model | Only the request text and up to three photos; resident PII is redacted from the analysis output |
| Transport | Requests go directly to your configured provider over TLS |
| Human-in-the-loop | AI suggestions (priority, category) require explicit staff approval before they take effect |
| Optional | AI can be turned off entirely; the platform runs without it |

Verify your chosen provider's data-handling terms (region, retention, whether inputs are used for training) against your jurisdiction's requirements.

### 📋 Document Retention Engine

State-specific record retention with legal hold protection:
- **Built-in policies**: TX (10yr), NJ/PA/WI (7yr), NY/MI/WA/CT (6yr), CA/FL/most states (5yr), GA/MA (3yr)
- **Admin-configurable**: Select state or custom period
- **Automatic enforcement**: Daily Celery Beat task archives expired records

#### Legal Holds
Records can be placed on **legal hold** via the `flagged` field to prevent automatic archival:
- **Per-request holds**: Staff can flag individual requests from the detail view
- **Audit trail**: All flag/unflag actions are logged with timestamp and user

#### Features that support compliance work

These features are designed to *support* the requirements below. They are not a certification, an audit, or a guarantee of compliance — meeting any given standard is the deploying jurisdiction's responsibility, and depends on how the system is configured and operated.

| Requirement | Supporting feature |
|-------------|--------------------|
| **Public records (OPRA / FOIA and equivalents)** | Export any request's full audit trail on demand; per-state retention schedules |
| **PII protection** | Field-level PII encryption at rest and TLS in transit |
| **Audit integrity** | Tamper-evident, hash-chained audit logs with a daily anchor |
| **Data minimization** | Optional PII anonymization for closed records; configurable retention |
| **Records administration** | Designated admin role for retention-policy management |


### ♿ Accessibility

Built toward **WCAG 2.1 Level AA**: keyboard navigation, a 4.5:1 contrast target, and aria-labels on interactive elements. This describes the design target, not an independent accessibility audit or certification. See [COMPLIANCE.md](./COMPLIANCE.md) for details.

---

## Deployment & Setup

### CI/CD Pipeline

Pinpoint 311 uses GitHub Actions for automated builds and security scanning:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| **Build & Publish** | Push to main | Multi-arch Docker images to GHCR |
| **CodeQL** | Push/PR + weekly | Static security analysis (Python/JS) |
| **Security Scan** | Push to main + weekly (Sundays) | OWASP ZAP + Trivy vulnerability scanning |
| **Accessibility** | Push to main | Pa11y accessibility audits |
| **Uptime Monitor** | Every 15 min | Health checks with auto-restart |
| **Load Test** | Manual dispatch | K6 performance benchmarking |
| **Dependabot** | Weekly | Automatic dependency updates |

### Self-Healing Infrastructure

The system automatically recovers from common failures without developer intervention:

| Layer | Protection | Config Required |
|-------|------------|-----------------|
| **Docker healthchecks** | Backend, Worker, Frontend auto-restart if unresponsive | None |
| **Container restart** | Containers restart after a crash (`unless-stopped`) | None |
| **Watchtower** | Optional: pulls updated images on a schedule | None |
| **SSH Auto-Restart** | Force restart via SSH when uptime check fails | Optional* |

*To enable SSH auto-restart, add `PROD_HOST` and `PROD_SSH_KEY` secrets to your GitHub repository.

### Resource Isolation

Prevents the 311 system from affecting other server systems:

| Service | CPU | Memory | Log Limit |
|---------|-----|--------|-----------|
| Database | 1 core | 1GB | 150MB |
| Backend | 1 core | 1GB | 150MB |
| Worker | 0.5 core | 512MB | 60MB |
| Frontend | 1 core | 512MB | 30MB |
| Redis | 0.25 core | 256MB | 30MB |
| Caddy | 0.25 core | 128MB | 60MB |

**Safety features:** `no-new-privileges` on all containers, Redis memory eviction, process limits on database.

### Docker Images

Pre-built images available on GitHub Container Registry:
```bash
ghcr.io/pinpoint-311/pinpoint-311-backend:latest
ghcr.io/pinpoint-311/pinpoint-311-frontend:latest
```

Supports both `linux/amd64` and `linux/arm64` architectures.

### Production Deployment (Recommended)

```bash
# Pull prebuilt images and deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Development Deployment

```bash
# Build locally (slower, for development only)
docker compose up --build -d
```

### Prerequisites
- Docker & Docker Compose
- A Google Maps API key — Maps is the one required external service. AI, translation, secret storage, notifications, and moderation are all optional and configured later in the browser.

### Quick Start (Using Prebuilt Images)
```bash
# 1. Clone the repository
git clone https://github.com/Pinpoint-311/Pinpoint-311.git
cd Pinpoint-311

# 2. Configure Environment
cp .env.example .env
# Edit .env and set your secrets (DB_PASSWORD, SECRET_KEY, etc.)

# 3. Pull prebuilt images and launch (recommended - fastest)
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# OR build locally (slower, for development/modifications)
# docker compose up --build -d
```

### Access Points (Production via Caddy)
- **Resident Portal**: `http://localhost/`
- **Staff Dashboard**: `http://localhost/staff`
- **Admin Console**: `http://localhost/admin`
- **Research Lab**: `http://localhost/research` *(requires researcher role)*
- **API Documentation**: `http://localhost/api/docs`

> [!TIP]
> In development without Caddy, the frontend runs at `http://localhost:5173` and the API at `http://localhost:8000`.

### Initial Setup & Authentication

Pinpoint 311 uses **Auth0 SSO** for all staff authentication.

#### Step 1: Configure Environment
```bash
cp .env.example .env
# Edit .env:
#   - DB_PASSWORD: Set a secure database password
#   - SECRET_KEY: Generate with `openssl rand -base64 32`
#   - DOMAIN: Your production domain (e.g., 311.yourtown.gov)
```

#### Step 2: Start Services
```bash
docker compose up -d
```

#### Step 3: Get Bootstrap Access
Before Auth0 is configured, use the bootstrap endpoint:
```bash
curl -X POST http://localhost/api/auth/bootstrap
```
Click the returned magic link → logs you into Admin Console.

#### Step 4: Configure Auth0 via Setup & Integration
In Admin Console → Setup & Integration:
1. Enter Auth0 domain, client ID, client secret
2. System encrypts and stores credentials securely
3. Bootstrap access is automatically disabled

#### Step 5: (Optional) Move secrets into an external vault
For stronger secret storage, configure your cloud's secret store in the Setup & Integration page. Credentials are then written to the vault and the database keeps only a reference.

#### Step 6: (Optional) Enable 45° Map Tilt & Rotation
For an immersive bird's eye map experience with 3D buildings, configure a **Google Maps Map ID**:

1. Go to [Google Cloud Console → Maps → Map Management](https://console.cloud.google.com/google/maps-apis/studio/maps)
2. Click **Create Map ID**
3. Select **Map type: Vector** and give it a name (e.g., "Pinpoint 311")
4. Copy the generated Map ID
5. In Admin Console → Secrets, add the key `GOOGLE_MAPS_MAP_ID` with the Map ID value

> [!TIP]
> Map ID enables the WebGL renderer with 45° tilt, compass rotation, and 3D buildings at no extra cost — same Dynamic Maps pricing ($7/1,000 loads, $200/month free credit).

### Security Storage

| Secret | Default Storage | Enterprise Storage |
|--------|-----------------|-------------------|
| DB Password | `.env` file | `.env` file |
| JWT Secret Key | `.env` file | `.env` file |
| Identity provider credentials | Database (Fernet encrypted) | External secret store |
| Integration & provider keys | Database (Fernet encrypted) | External secret store (reference only in DB) |

> [!NOTE]
> Bootstrap access is automatically disabled once Auth0 is configured. All future logins use SSO.

---

## Centralized Hosting (Managed Mode)

**Self-hosting is the default, and it is complete on its own.** A single town runs its own instance, owns its data, and needs nothing else in this section. Everything above describes that standalone deployment.

Centralized hosting is a **separate, optional** feature for a different situation: a state, county, or agency that wants to stand up and run instances for *many* towns at once — including towns that could never manage their own server. It changes nothing about how a self-hosted deployment works, and no self-hosted town depends on it. The orchestrator that drives it lives in its own repository, **[Pinpoint-311/centralizedhosting](https://github.com/Pinpoint-311/centralizedhosting)**; this repository only contains the optional, flag-gated hooks that let an instance *be* driven by one.

When used, the model is:

**Every town stays fully isolated.** One instance equals one jurisdiction, each with its own database, storage, encryption key, and secrets — the same isolation a self-hosted town has. There are no shared tables and no cross-town data; one town's resident data never mixes with another's.

**A separate control plane provisions and monitors the fleet.** Instead of logging into many servers by hand, the operator uses the orchestrator to provision new town instances and inject only platform-managed settings (infrastructure, backups, domain); roll out new versions safely, gated on the version and database-revision stamp each instance reports on its health endpoint; suspend and resume instances; and aggregate health, uptime, and cost metadata across the fleet.

**The control plane never touches resident data.** Its job is infrastructure, platform secrets, version rollout, and aggregate metadata — nothing more. Everything a town's staff and residents do stays inside that town's own instance.

**It is opt-in and a no-op when off.** With `MANAGED_MODE` off (the default), the app behaves exactly as the standalone single-tenant deployment described throughout this README. With it on, flag-gated hooks let the control plane own infrastructure settings while the town keeps control of its own services and content; platform-owned settings appear as "Managed by your state" and are locked in the Admin Console. The app-side hooks (provisioning and telemetry APIs behind a token, managed settings, health/version stamping, and lifecycle controls) live here; the orchestrator itself is maintained in its own repository.

---

## Security & Governance

Pinpoint 311 is designed for municipal government use, handling sensitive resident data. We take security, privacy, and supply-chain integrity seriously.

### 🔒 Reporting Vulnerabilities

**DO NOT** file a public issue for security vulnerabilities. Publicly disclosing a vulnerability puts live deployments at risk.

We use GitHub's **Private Vulnerability Reporting** to handle disclosures securely:

1. Go to the [**Security** tab](https://github.com/Pinpoint-311/Pinpoint-311/security) in this repository.
2. Click on **"Report a vulnerability"** to open a private advisory.
3. Describe the vulnerability. This opens a private communication channel visible *only* to the project maintainers.

We aim to acknowledge all reports within 48 hours.

### 🏗️ Zero-Trust Governance Model

To maintain the integrity required for government software:

| Access Type | Policy |
|-------------|--------|
| **Read Access** | Code is open-source and auditable by anyone |
| **Write Access** | Merge rights restricted to Core Maintainers only |
| **Review Process** | All PRs undergo mandatory security review before merging |
| **Dependencies** | All dependencies pinned to specific versions to prevent supply-chain attacks |

### Supported Versions

| Version | Supported | Notes |
| :--- | :---: | :--- |
| **Latest Stable** | | Current production release |
| **Main branch** | Development only | Unstable builds |
| **< 1.0.0** | Unsupported | Legacy versions |

### 🛑 Out of Scope

The following are generally considered out of scope for security reports:
- Attacks requiring physical access to the user's device
- Social engineering attacks against staff
- Clickjacking on pages with no sensitive actions
- Reports from automated scanners without validated proof of concept

---

## Sustainability & Continuity

**Can this system stand on its own if Pinpoint 311 disappears tomorrow?**

Yes. Every deployment is self-hosted on your own infrastructure.

| Aspect | Details |
|--------|---------|
| **Code ownership** | Full source code runs on your server |
| **Data ownership** | The PostgreSQL database is yours to control |
| **License** | MIT — fork, modify, and redistribute freely |
| **Dependencies** | Open-source, with public documentation |
| **Phone-home** | The application makes no calls back to Pinpoint 311 servers |
| **Recovery** | Container auto-restart and health checks |
| **Updates** | Optional automatic image updates (see below) |

**Watchtower (Optional):**
Watchtower automatically updates your Docker containers with security patches. It runs at 3am daily.

```bash
# Enable Watchtower
docker compose up -d watchtower

# Disable Watchtower  
docker compose stop watchtower

# Check status
docker compose ps watchtower
```

> 💡 The core system works perfectly without Watchtower. Enable it for hands-off security updates, or disable it for full manual control.

**What you'd handle independently:**
- Security patches for dependencies
- New features and bug fixes
- Any developer familiar with Python/FastAPI + React can maintain this codebase

---

## License

Pinpoint 311 is open-source software licensed under the [MIT License](LICENSE).

---

## Fiscal Sponsorship

Pinpoint 311 is fiscally sponsored by **[The Hack Foundation](https://hackclub.com/fiscal-sponsorship/)** (d.b.a. Hack Club), a 501(c)(3) public charity (EIN: 81-2908499). Hack Club provides fiscal sponsorship infrastructure, allowing Pinpoint 311 to receive tax-deductible donations on our behalf while we focus on building civic technology.

Donations to Pinpoint 311 are tax-deductible to the extent permitted by law.

<p align="center">
  Built by Pinpoint 311 for Civic Engagement<br>
  <a href="https://hcb.hackclub.com/pinpoint-311"><img src="https://img.shields.io/badge/Fiscally%20Sponsored%20by-Hack%20Club-ec3750.svg" alt="Fiscally Sponsored by Hack Club"></a>
</p>
