# Pinpoint 311 - Advanced Municipal Request System

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg" alt="React 18">
  <img src="https://img.shields.io/badge/FastAPI-0.109-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-15-336791.svg" alt="PostgreSQL 15">
  <img src="https://img.shields.io/badge/AI-Gemini%203.0-8E24AA.svg" alt="Gemini 3.0 Flash">
  <img src="https://img.shields.io/badge/Geo-PostGIS-336791.svg" alt="PostGIS">
</p>

<p align="center">
  <a href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/build-publish.yml"><img src="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/build-publish.yml/badge.svg" alt="Build Status"></a>
  <a href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/codeql.yml"><img src="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
  <a href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/security-scan.yml"><img src="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/security-scan.yml/badge.svg" alt="Security Scan"></a>
  <a href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/accessibility.yml"><img src="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/actions/workflows/accessibility.yml/badge.svg" alt="Accessibility"></a>
</p>

## 🏛️ Introduction

Pinpoint 311 is a production-grade, open-source platform designed for modern municipalities. It replaces legacy, clunky government forms with a **consumer-grade user experience** that feels as polished as a ride-sharing or food-delivery app.

Beyond the UI, it features a sophisticated **AI & Geospatial Engine** that automates triage, detects duplicate reports, and routes requests based on precise location data—saving thousands of staff hours manually sorting tickets.

---

## 📑 Table of Contents

- [Why Pinpoint?](#-why-pinpoint)
- [Choose Your Experience](#-choose-your-experience)
- [Core Features Overview](#-core-features-overview)
- [Resident Portal Features](#-resident-portal-features)
- [Staff Dashboard Features](#-staff-dashboard-features)
- [Admin Console Features](#️-admin-console-features)
- [Research Suite](#-research-suite-university-lab-integration)
- [Technical Architecture](#-technical-architecture)
- [Deployment & Setup](#-deployment--setup)
- [Roadmap](#️-roadmap)
- [Security & Governance](#-security--governance)
- [License](#-license)

---

## ⚡ Why Pinpoint?

### Feature Comparison

| Feature | Legacy Forms | SeeClickFix / Commercial | **Pinpoint 311** |
| :--- | :---: | :---: | :---: |
| **Pricing** | Free (DIY) | $5-20K/year | **Free & Open Source** |
| **Data Ownership** | ✅ You own | ❌ Vendor-hosted | **✅ Self-hosted** |
| **Source Code** | N/A | ❌ Proprietary | **✅ MIT License** |
| **Mobile Experience** | Non-responsive | Native apps | **PWA (No App Store)** |
| **AI Triage** | ❌ Manual | ❌ Basic rules | **✅ Gemini 3.0 Flash** |
| **Photo Analysis** | ❌ None | ❌ None | **✅ Vision AI** |
| **Multilingual** | ❌ English | ~10 languages | **✅ 130+ languages** |
| **Resident Login** | Required | Required | **✅ No account needed** |
| **Live Tracking** | ❌ None | ✅ Email only | **✅ SMS + Email + Magic Link** |
| **Location Accuracy** | Text address | GPS pin | **✅ GPS + Asset Snapping** |
| **PII Protection** | ❌ None | ⚠️ Basic | **✅ Auto-Redacted + KMS** |
| **Geofencing** | ❌ None | ⚠️ Limited | **✅ PostGIS Boundaries** |
| **Research Export** | ❌ None | ⚠️ Extra cost | **✅ 60+ fields, free** |
| **Custom Branding** | DIY | ⚠️ Limited | **✅ Full white-label** |
| **Self-Healing** | ❌ None | ❌ Managed | **✅ Auto-restart + Watchtower** |

### The Bottom Line

> **SeeClickFix and similar platforms charge $5,000-20,000/year**, lock you into their cloud, and own your data. Pinpoint 311 gives you **the same (or better) features for free**, with full data sovereignty and no vendor lock-in.

---

## 🎭 Choose Your Experience

<table>
<tr>
<td width="25%" align="center">

### 🏠 Resident
**Report issues in 60 seconds**

✅ No account needed<br>
✅ 130+ languages<br>
✅ Track via magic link<br>
✅ Photo uploads

<a href="#-resident-portal-features">→ Features</a>

</td>
<td width="25%" align="center">

### 👷 Staff
**Manage & resolve requests**

✅ AI-powered triage<br>
✅ Priority scoring<br>
✅ Department routing<br>
✅ Internal comments

<a href="#-staff-dashboard-features">→ Features</a>

</td>
<td width="25%" align="center">

### ⚙️ Admin
**Configure everything**

✅ Service categories<br>
✅ Custom branding<br>
✅ API key management<br>
✅ User & role control

<a href="#️-admin-console-features">→ Features</a>

</td>
<td width="25%" align="center">

### 🔬 Researcher
**Analyze municipal data**

✅ 60+ research fields<br>
✅ Privacy-preserved<br>
✅ CSV & GeoJSON export<br>
✅ Census integration

<a href="#-research-suite-university-lab-integration">→ Features</a>

</td>
</tr>
</table>

<details>
<summary><b>📊 System Architecture</b> (click to expand)</summary>

```mermaid
graph TB
    subgraph "Frontend"
        RP[Resident Portal]
        SP[Staff Dashboard]
        AC[Admin Console]
    end

    subgraph "Backend Services"
        API[FastAPI Server]
        WK[Celery Worker]
        RD[(Redis Cache)]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL + PostGIS)]
    end

    subgraph "External Services"
        VA[Vertex AI - Gemini]
        GM[Google Maps]
        GT[Google Translate]
        SM[SMTP / SMS]
        A0[Auth0 SSO]
    end

    RP --> API
    SP --> API
    AC --> API
    
    API --> PG
    API --> RD
    API --> WK
    
    WK --> SM
    WK --> VA
    
    API --> GM
    API --> GT
    API --> A0
```

</details>

<details>
<summary><b>🔄 Request Lifecycle</b> (click to expand)</summary>

```mermaid
flowchart LR
    A[📱 Resident Submits] --> B{Within Boundary?}
    B -->|No| C[❌ Rejected]
    B -->|Yes| D[✅ Created]
    
    D --> E[🤖 AI Analysis]
    E --> F[📧 Confirmation Email]
    
    F --> G[👷 Staff Reviews]
    G --> H{Action?}
    
    H -->|Assign| I[📋 In Progress]
    H -->|Resolve| J[✅ Resolved]
    H -->|Transfer| K[↗️ Third Party]
    
    I --> J
    J --> L[📧 Closure Email]
```

</details>

<details>
<summary><b>🔐 Security Stack</b> (click to expand)</summary>

```mermaid
graph LR
    subgraph "Identity"
        A0[Auth0 SSO]
        MFA[MFA / Passkeys]
    end

    subgraph "Secrets"
        GSM[Google Secret Manager]
        KMS[Cloud KMS - PII]
    end

    subgraph "Infrastructure"
        WT[Watchtower Auto-Updates]
        CD[Caddy HTTPS]
    end

    A0 --> MFA
    GSM --> KMS
    WT --> CD
```

</details>

## 🌟 Core Features Overview

### 🎨 User Experience First
- **Premium Glassmorphism Design**: A modern, translucent UI that builds trust and engagement.
- **Mobile-First Architecture**: Fully responsive web app that behaves natively on iOS/Android.
- **130+ Language Support**: Powered by Google Translate API with intelligent caching. **Complete translation coverage**: UI strings, service categories, status labels, filter buttons, priority levels, search placeholders, and user-submitted content are automatically translated. **Automatic notification translation**: All confirmation emails and SMS messages are sent in the resident's selected language—no additional configuration needed.
- **No-Login Submission**: Removes friction for residents while maintaining security via email magic links.

### 🧠 Advanced Intelligence
- **Information Redaction**: Automatically strips PII (names, phones, emails) from public request logs.
- **Visual Analysis**: Uses **Gemini 3.0 Flash** via Google Cloud **Vertex AI** to "see" uploaded photos and categorize hazards (e.g., "pothole caused by water damage").
- **Multilingual AI Analysis**: When residents submit requests in non-English languages, the AI automatically provides a literal English translation first before performing its analysis, ensuring staff can understand all submissions regardless of language.
- **Priority Scoring (Human-in-the-Loop)**: AI suggests a 1-10 urgency score, but scores are **never automatically saved**. Staff must explicitly accept or override the AI suggestion, ensuring human accountability for all priority decisions.

### 🗺️ Geospatial Power
- **Asset Matching**: snaps user pins to verified infrastructure (e.g., streetlights, hydrants) using PostGIS `ST_DWithin`.
- **Boundary Enforcement**: Validates that requests are actually within township limits before submission.
- **Heatmaps & Clustering**: Auto-groups nearby requests to visualize problem hotspots.

---

## 🏠 Resident Portal Features

The Resident Portal is the public face of the system, designed for zero friction.

### 1. Service Discovery
- **Visual Grid**: Services are displayed with clear, consistent iconography (Lucide React) for instant recognition.
- **Service Categories**: Browsable catalog of all available township services.

### 2. Intelligent Location Picker
- **Interactive Map**: Google Maps integration with drag-to-set pin functionality.
- **Address Autocomplete**: Type-ahead search for local addresses.
- **Jurisdiction Boundaries**: System-level polygons (GeoJSON) define the valid service area. PINS dropped outside are auto-rejected.
- **Asset Integration**: Requests can be linked to specific infrastructure assets (e.g., specific park zones) if configured.

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

## 👷 Staff Dashboard Features

The Staff Dashboard is the command center for municipal operations, protected by secure JWT authentication.

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
- **Audit Log**: Immutable history of every action (status change, assignment, comment).

### 3. Request Management
- **Smart Assignment**: Auto-route to specific departments or keep in a general queue.
- **Completion Types**: Close requests as **Resolved** (with photo proof), **No Action Needed** (invalid), or **Transferred** (third-party).
- **Priority Override**: Manually escalate issues that AI might have missed.
- **Asset History**: When viewing a request attached to a physical asset (e.g., Hydrant #404), automatically shows all past history for that specific asset.
- **Status Workflow**:
    - **Open**: New request.
    - **In Progress**: Staff acknowledged and working.
    - **Resolved**: Work complete.
    - **Closed**: Final state (includes optional "Completion Photo" proof).

### 4. AI Insights Panel (Vertex AI Powered)
- **Safety Flags**: Highlights potential liabilities (e.g., "Downed power line detected").
- **Proximity Analysis**: Checks if the issue is near critical infrastructure (Schools, Hospitals, Fire Stations) via PostGIS, with a **Nominatim (OpenStreetMap)** fallback for unmapped areas.
- **Sentiment Analysis**: Gauges the tone of the resident's description (Neutral, Frustrated, Urgent).
- **Weather Context**: Automatically fetches real-time weather (e.g., "Heavy Rain, 45°F") to validiate hazards.
- **Gemini 3.0 Flash**: Powered by Google's latest model with "Thinking Config" for deep reasoning and lower latency.
- **Duplicate Detection**: Suggests potential duplicate reports based on location (within 50m) and time window.
- **Human-in-the-Loop Priority**: AI priority suggestions are stored in a JSON field and displayed with an **"Accept AI Priority"** button. Staff must explicitly accept the score before it becomes the official priority, creating a complete audit trail.
- **PostGIS Geospatial Analytics**:
    - **Hotspot Analysis**: Automatically clusters requests to identify problem areas (e.g., "Pothole Clusters" on specific roads).
    - **User Bias Detection**: Flags suspicious activity using spatial statistics (e.g., single user spamming requests in a 10m radius).
    - **Jurisdiction Verification**: Real-time point-in-polygon checks against township boundaries.

---

## ⚙️ Admin Console Features

A full CMS for managing the municipality's presence without touching code.

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
- **Key Management**: Securely store API keys for Google Maps, Vertex AI (Google Cloud Project ID + Service Account Key), and SMS Providers.
- **Feature Modules**: Toggle major features like "AI Analysis" or "SMS Alerts" on/off globally.
    - `ENABLE_SMS_ALERTS`: Toggle text message notifications (Twilio or Generic).
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
  
- **Accessibility Statement**: Customizable Markdown covering ADA/WCAG compliance. Default includes:
  - WCAG 2.1 Level AA commitment
  - Section 508 compliance
  - Alternative submission methods (phone, email, in-person)
  - Contact information for accessibility concerns

All legal pages are editable via **Admin Console → Branding → Legal Documents**.

---

## ⚠️ Non-Emergency Disclaimer System

Built-in legal protection ensuring residents understand 311 is for non-emergency municipal services only.

### One-Time Acknowledgment Modal
- **Premium Design**: Glassmorphism modal matching portal aesthetic
- **Checkbox Confirmation**: Users must actively acknowledge before accessing portal
- **localStorage Persistence**: Shows once per browser, doesn't repeatedly annoy returning users

### Persistent Warning Banner
- **Always Visible**: Amber gradient banner at top of resident portal
- **Clear Messaging**: "**Non-Emergency Only** — For police, fire, or medical emergencies, call **911**"

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

## 📊 Research Suite (University Lab Integration)

A privacy-preserving analytics layer designed for external university researchers studying municipal operations, infrastructure, equity, and civic engagement. Exports **60+ research fields** computed on-the-fly from **real data sources**.

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

### 📦 Research Packs (5 Specialized Domains)

#### 🟣 Social Equity Pack (Sociologists)
Real census data integration for equity research.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `census_tract_geoid` | string | 11-digit FIPS code for Census joins | US Census Geocoder API ✅ |
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
| `weather_precip_24h_mm` | float | Precipitation 24h before report | Open-Meteo Archive API ✅ |
| `weather_temp_max_c` | float | Max temperature on report day | Open-Meteo Archive API ✅ |
| `weather_temp_min_c` | float | Min temperature on report day | Open-Meteo Archive API ✅ |
| `weather_code` | int | WMO weather code (61=rain, 71=snow) | Open-Meteo Archive API ✅ |
| `nearby_asset_age_years` | float | Age of matched infrastructure | Asset properties |
| `matched_asset_attributes` | JSON | Full asset properties (pressure_psi, acres, bulb type) | GeoJSON layer ✅ |
| `season` | string | winter/spring/summer/fall | Calculated |

**Suggested Analyses**: Freeze-thaw pothole correlation, asset survival analysis, precipitation-drainage linkage

---

#### 🩷 Sentiment & Trust Pack (Political Scientists)
NLP-derived indicators of civic trust and satisfaction.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `sentiment_score` | float (-1 to +1) | NLP sentiment (-1=angry, +1=grateful) | Word-based NLP ✅ |
| `is_repeat_report` | boolean | Text indicates prior report of same issue | Regex detection ✅ |
| `prior_report_mentioned` | boolean | References ticket/case number | Regex detection ✅ |
| `frustration_expressed` | boolean | Trust erosion indicators present | Regex detection ✅ |

**Suggested Analyses**: Sentiment vs income quintile, repeat report resolution rates, trust erosion over time

---

#### 🟠 Bureaucratic Friction Pack (Public Administration)
Quantified measures of administrative efficiency and government responsiveness.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `time_to_triage_hours` | float | Hours from submission to first "In Progress" | Audit logs ✅ |
| `reassignment_count` | int | Times request bounced between departments | Audit logs ✅ |
| `off_hours_submission` | boolean | Submitted before 6am or after 10pm | Timestamp ✅ |
| `escalation_occurred` | boolean | Priority manually increased by staff | Audit logs ✅ |
| `total_hours_to_resolve` | float | Total clock hours to closure | Calculated ✅ |
| `business_hours_to_resolve` | float | Business hours only (Mon-Fri 8am-5pm) | Calculated ✅ |
| `days_to_first_update` | float | Days until first staff action | Calculated ✅ |
| `status_change_count` | int | Number of status changes | Audit logs ✅ |

**Suggested Analyses**: Triage time vs resolution outcome, department routing efficiency, off-hours urgent patterns

---

#### 🟢 AI/ML Research Pack (Data Scientists)
Training data for AI systems and human-AI alignment studies.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `ai_flagged` | boolean | AI flagged for staff review | Vertex AI ✅ |
| `ai_flag_reason` | string | Reason for flag (safety, urgent) | Vertex AI ✅ |
| `ai_priority_score` | float (1-10) | AI-generated priority | Vertex AI ✅ |
| `ai_classification` | string | AI-assigned category | Vertex AI ✅ |
| `ai_summary_sanitized` | string | AI summary (PII redacted) | Vertex AI ✅ |
| `ai_analyzed` | boolean | Whether AI processed this request | System ✅ |
| `ai_vs_manual_priority_diff` | float | manual_priority - ai_priority | Calculated ✅ |

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
| **Vertex AI** | ai_* fields | If AI analysis is enabled |

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

## 🚀 Technical Architecture

### Communication Engine
- **Branding Engine**: Automatically injects township logo, colors, and font settings into every email.
- **Rich SMS**: Sends text alerts with status emojis (✅, 🚧), request details (category, address), and magic links for instant tracking.
- **Provider Agnostic**: Built-in support for **Twilio**, plus a generic HTTP adapter for any other SMS gateway.
- **Completion Proof**: "Review & Close" workflow attaches the final resolution photo to the closing email sent to the resident.

### Standards Compliance
- **Open311 v2**: Fully compliant with the Open311 GeoReport v2 standard (JSON).
    - `GET /requests.json`: Public feed (cached via Redis).
    - `POST /requests.json`: Standard submission endpoint.
- **Audit Trails**: Every action (submission, comment, status change) is logged for accountability.

### Tech Stack
| Component | Technology | Description |
|-----------|------------|-------------|
| **Frontend** | React 18 + TypeScript | Performant, type-safe UI built with Vite |
| **Styling** | Tailwind CSS + Framer Motion | Fluid animations and glassmorphism themes |
| **Backend** | FastAPI (Python 3.11) | High-performance async REST API |
| **Database** | PostgreSQL 15 + PostGIS | Relational data with advanced spatial queries |
| **Migrations** | Alembic | Version-controlled database schema changes |
| **Caching** | Redis | High-speed caching for public request feeds (60s TTL) |
| **AI** | Vertex AI (Gemini Flash) | Multimodal model for image/text analysis |
| **Queue** | Celery + Redis | Background processing for emails and reports |
| **Reverse Proxy** | Caddy | Automatic HTTPS and SSL termination |

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

#### Enterprise Security Stack
Pinpoint 311 implements a production-grade security stack with managed cloud services:

| Component | Purpose | Provider |
|-----------|---------|----------|
| **Auth0** | SSO with MFA & Passkeys | Managed Identity |
| **Google Secret Manager** | API keys & credentials | Google Cloud |
| **Google Cloud KMS** | Resident PII encryption | Google Cloud |
| **Watchtower** | Container auto-updates | Self-hosted |

#### Zero-Password Authentication
Staff login via **Auth0** with enterprise-grade security:
- **Multi-Factor Authentication**: TOTP, passkeys, and biometric support
- **Social Login**: Google, Microsoft, and other identity providers
- **Passwordless Option**: WebAuthn/passkeys for phishing resistance
- **No passwords stored**: Authentication fully delegated to Auth0

#### Secrets Management
Two-tier security for credentials:

| Secret Type | Storage | Encryption |
|-------------|---------|------------|
| API Keys (SMTP, SMS, Maps) | Google Secret Manager | Google-managed HSMs |
| Resident PII (email, phone, name) | PostgreSQL | Google Cloud KMS (AES-256) |
| Local Development | Encrypted Database | Fernet (AES-128-CBC) |


#### GCP Service Account Authentication
Pinpoint 311 uses **encrypted service account keys** for Google Cloud access:

```
┌─────────────┐    Fernet Encrypted    ┌──────────────────┐    Direct Auth    ┌─────────────┐
│   Backend   │ ─────────────────────▶ │ PostgreSQL DB    │ ────────────────▶ │ GCP APIs    │
│   (FastAPI) │                        │ (system_secrets) │                   │ SM, KMS, AI │
└─────────────┘                        └──────────────────┘                   └─────────────┘
```

**How it works:**
1. Upload service account JSON during initial setup
2. Key is encrypted with Fernet (AES-128-CBC) using `SECRET_KEY`
3. Stored securely in the `system_secrets` database table
4. Decrypted at runtime when accessing GCP services

**Bootstrap Keys:**
Two keys must remain in the local database (not migrated to Secret Manager):
- `GCP_SERVICE_ACCOUNT_JSON`: The encrypted service account key
- `GOOGLE_CLOUD_PROJECT`: The GCP project ID

These "bootstrap keys" are needed to *access* Secret Manager itself, so they must be stored locally.


#### API & Infrastructure Security
- **Rate Limiting**: 500 requests/minute per IP (slowapi)
- **Security Headers**: X-Frame-Options, CSP, nosniff, XSS protection
- **RBAC**: Staff, Researcher, Admin roles with JWT authentication
- **Input Validation**: Pydantic schemas, SQLAlchemy ORM (SQL injection proof)
- **Audit Logging**: Immutable trail of all request lifecycle events

For full security details, see [COMPLIANCE.md](./COMPLIANCE.md).

#### Vertex AI Security
| Feature | Protection |
|---------|------------|
| Data Residency | Stays within configured GCP region |
| Encryption | TLS 1.3+ in transit, AES-256 at rest |
| No Data Training | Customer data NOT used for training |
| Certifications | SOC 1/2/3, ISO 27001, FedRAMP, HIPAA |
| Human-in-the-Loop | AI suggestions require staff approval |

### 📋 Document Retention Engine

State-specific record retention with legal hold protection:
- **Built-in policies**: TX (10yr), NJ/PA/WI (7yr), NY/MI/WA (6yr), CA/FL/others (3-5yr)
- **Admin-configurable**: Select state or custom period
- **Automatic enforcement**: Daily Celery task archives expired records

#### Legal Holds
When litigation or investigation is anticipated, records can be placed on **legal hold** to prevent automatic deletion:
- **Per-request holds**: Staff can flag individual requests as "Legal Hold" from the detail view
- **Bulk holds**: Admin can apply holds to all requests matching specific criteria (date range, category, location)
- **Hold expiration**: Optional expiration date, or indefinite hold until manually released
- **Audit trail**: All hold/release actions are logged with timestamp and user

#### Compliance Features
| Requirement | Implementation |
|-------------|----------------|
| **OPRA (NJ) / FOIA** | Export any request's full audit trail on demand |
| **CJIS** | PII encryption at rest (AES-256) and in transit (TLS 1.3) |
| **NIST 800-53** | Immutable audit logs with tamper detection |
| **GDPR/CCPA** | PII anonymization option for closed records |
| **Records Officer** | Designated admin role for retention policy management |


### ♿ Accessibility (WCAG 2.2 AA)

Full keyboard navigation, 4.5:1 contrast ratio, proper aria-labels on all interactive elements. See [COMPLIANCE.md](./COMPLIANCE.md) for details.

---

## 📦 Deployment & Setup

### CI/CD Pipeline

Pinpoint 311 uses GitHub Actions for automated builds and security scanning:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| **Build & Publish** | Push to main | Multi-arch Docker images to GHCR |
| **CodeQL** | Push/PR + weekly | Static security analysis (Python/JS) |
| **Security Scan** | Push + weekly | OWASP ZAP + Trivy vulnerability scanning |
| **Uptime Monitor** | Every 15 min | Health checks with auto-restart |
| **Dependabot** | Weekly | Automatic dependency updates |

### Self-Healing Infrastructure

The system automatically recovers from common failures without developer intervention:

| Layer | Protection | Config Required |
|-------|------------|-----------------|
| **Docker Healthchecks** | Backend, Worker, Frontend auto-restart if unresponsive | None ✅ |
| **Container Restart** | Containers restart after crash (`unless-stopped`) | None ✅ |
| **Watchtower** | Auto-pulls security updates at 3am daily | None ✅ |
| **SSH Auto-Restart** | Force restart via SSH when uptime check fails | Optional* |

*To enable SSH auto-restart, add `PROD_HOST` and `PROD_SSH_KEY` secrets to your GitHub repository.

### Resource Isolation

Prevents the 311 system from affecting other server systems:

| Service | CPU | Memory | Log Limit |
|---------|-----|--------|-----------|
| Database | 1 core | 1GB | 150MB |
| Backend | 1 core | 1GB | 150MB |
| Worker | 0.5 core | 512MB | 60MB |
| Frontend | 0.5 core | 256MB | 30MB |
| Redis | 0.25 core | 256MB | 30MB |
| Caddy | 0.25 core | 128MB | 60MB |

**Safety features:** `no-new-privileges` on all containers, Redis memory eviction, process limits on database.

### Docker Images

Pre-built images available on GitHub Container Registry:
```bash
ghcr.io/westwindsorforward/wwf-311-backend:latest
ghcr.io/westwindsorforward/wwf-311-frontend:latest
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
- A Google Cloud Project (for Maps & Vertex AI)

### Quick Start (Using Prebuilt Images)
```bash
# 1. Clone the repository
git clone https://github.com/WestWindsorForward/WWF-Open-Source-311-Template.git
cd WWF-Open-Source-311-Template

# 2. Configure Environment
cp .env.example .env
# Edit .env and set your secrets (DB_PASSWORD, SECRET_KEY, etc.)

# 3. Pull prebuilt images and launch (recommended - fastest)
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# OR build locally (slower, for development/modifications)
# docker compose up --build -d
```

### Access Points
- **Resident Portal**: `http://localhost/`
- **Staff Dashboard**: `http://localhost/staff`
- **Admin Console**: `http://localhost/admin`
- **Research Lab**: `http://localhost/research` *(requires researcher role)*
- **API Documentation**: `http://localhost/api/docs`

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

#### Step 4: Configure Auth0 via Setup Wizard
In Admin Console → Setup Wizard:
1. Enter Auth0 domain, client ID, client secret
2. System encrypts and stores credentials securely
3. Bootstrap access is automatically disabled

#### Step 5: (Optional) Enable Google Secret Manager
For enterprise-grade secret storage, configure GCP in the Setup Wizard. Secrets will be migrated from the database to Google Secret Manager.

### Security Storage

| Secret | Default Storage | Enterprise Storage |
|--------|-----------------|-------------------|
| DB Password | `.env` file | `.env` file |
| JWT Secret Key | `.env` file | `.env` file |
| Auth0 Credentials | Database (Fernet encrypted) | Google Secret Manager |
| API Keys | Database (Fernet encrypted) | Google Secret Manager |

> [!NOTE]
> Bootstrap access is automatically disabled once Auth0 is configured. All future logins use SSO.

---

## 🗺️ Roadmap

- [x] AI Triage & Gemini 3.0 Integration
- [x] PostGIS Asset Snapping & Geofencing
- [x] Multi-Language Support (130+ languages)
- [ ] iOS/Android Native App Wrappers (Capacitor)
- [ ] 3rd Party CRM Integrations (Salesforce, GovPilot)
- [ ] Offline Mode for Field Staff
- [ ] Push Notifications for Mobile

---

## 🛡️ Security & Governance

Pinpoint 311 is designed for municipal government use, handling sensitive resident data. We take security, privacy, and supply-chain integrity seriously.

### 🔒 Reporting Vulnerabilities

**DO NOT** file a public issue for security vulnerabilities. Publicly disclosing a vulnerability puts live deployments at risk.

We use GitHub's **Private Vulnerability Reporting** to handle disclosures securely:

1. Go to the [**Security** tab](https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/security) in this repository.
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

### ✅ Supported Versions

| Version | Supported | Notes |
| :--- | :---: | :--- |
| **Latest Stable** | ✅ | Current production release |
| **Main Branch** | ⚠️ | Development builds (unstable) |
| **< 1.0.0** | ❌ | Legacy versions |

### 🛑 Out of Scope

The following are generally considered out of scope for security reports:
- Attacks requiring physical access to the user's device
- Social engineering attacks against staff
- Clickjacking on pages with no sensitive actions
- Reports from automated scanners without validated proof of concept

---

## 🔄 Sustainability & Continuity

**Can this system stand on its own if Pinpoint 311 disappears tomorrow?**

**Yes.** Every deployment is 100% self-hosted on YOUR infrastructure.

| Aspect | Status |
|--------|--------|
| **Code Ownership** | ✅ Full source code on your server |
| **Data Ownership** | ✅ PostgreSQL database you control |
| **License** | ✅ MIT - fork, modify, redistribute freely |
| **Dependencies** | ✅ All open-source with public documentation |
| **Phone-Home** | ✅ None - no calls to Pinpoint 311 servers |
| **Self-Healing** | ✅ Auto-restart, health checks |
| **Watchtower** | ✅ Optional auto-updates (see below) |

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

## 📄 License

Pinpoint 311 is open-source software licensed under the [MIT License](LICENSE).

<p align="center">
  Built by Pinpoint 311 for Civic Engagement
</p>
