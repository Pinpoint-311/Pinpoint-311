# Government Compliance & Security Posture

The Pinpoint 311 platform is designed for on-premises deployment within municipal jurisdictions, prioritizing data sovereignty, administrative accountability, and regulatory compliance.

---

## 1. Government-Ready Core Features

### Data Sovereignty
- **On-Premises Deployment**: Containerized via Docker for deployment behind municipal firewalls
- **Configurable PII Handling**:
  - **Cloud Mode**: PII encrypted via Google Cloud KMS (data transits to GCP for encryption, stored encrypted locally)
  - **Local Mode**: PII encrypted via Fernet locally (no cloud dependency, `SECRET_KEY` based)
- **No Third-Party Analytics**: No external tracking or analytics services

### Audit Logging
- **Comprehensive Trail**: Every lifecycle event recorded in `request_audit_logs` table
- **Actions Tracked**: Submission, assignment, status changes, comments, edits
- **Immutable Ledger**: Write-only audit design for legal discovery and institutional memory

### Role-Based Access Control (RBAC)

| Role | Access Level |
|------|--------------|
| **Resident** | Public submission, track own requests (ID required), no PII visibility |
| **Staff** | Department-scoped or global request management, internal comments |
| **Admin** | System-wide control: users, departments, branding, API keys |

### Open311 Compliance
- **GeoReport v2**: Standard-compliant API for interoperability
- **Service Discovery**: XML/JSON endpoint at `/api/services/`
- **Third-Party Integration**: Compatible with Open311 reporter apps

---

## 2. Security Posture

### Enterprise Security Stack

Pinpoint 311 implements a production-grade, managed security stack:

| Component | Purpose | Provider |
|-----------|---------|----------|
| **Zitadel Cloud** | SSO with MFA & Passkeys | Managed Identity |
| **Google Secret Manager** | API keys & credentials | Google Cloud |
| **Google Cloud KMS** | Resident PII encryption | Google Cloud |
| **Watchtower** | Container auto-updates | Self-hosted |

### Zero-Password Authentication (Zitadel Cloud)

Staff login via **Zitadel Cloud SSO** eliminates password-related vulnerabilities:

| Feature | Implementation |
|---------|----------------|
| Authentication | Zitadel Cloud OIDC with JWT tokens |
| Multi-Factor | TOTP, passkeys, biometric support |
| Session Management | JWT tokens with 8-hour expiration |
| Passwordless | WebAuthn/passkeys for phishing resistance |
| Social Login | Google, Microsoft identity providers |
| Password Storage | **None** - fully delegated to Zitadel |

### Secrets Management (Google Secret Manager)

API credentials stored in Google Secret Manager with HSM-backed encryption:

| Property | Value |
|----------|-------|
| Storage | Google Cloud Secret Manager |
| Encryption | Google-managed HSMs (AES-256-GCM) |
| Access Control | IAM + VPC controls |
| Audit Logging | Full access logs in Cloud Audit |
| Free Tier | 6 active secret versions (bundled secrets) |

**Protected Secrets (6 Bundles):**
- `secret-zitadel`: SSO credentials
- `secret-smtp`: Email configuration
- `secret-sms`: SMS provider keys
- `secret-google`: Maps, Vertex AI credentials
- `secret-backup`: S3/backup configuration
- `secret-config`: Township-specific settings

### PII Encryption (Google Cloud KMS)

Resident personal information encrypted with Google Cloud KMS:

| Property | Value |
|----------|-------|
| Algorithm | AES-256-GCM (HSM-backed) |
| Key Management | Google-managed, automatic rotation |
| Protected Fields | Email, phone, name, address |
| Audit Trail | Cloud Audit Logs for all encrypt/decrypt |
| Compliance | SOC 2, ISO 27001, FedRAMP eligible |

### Container Auto-Updates (Watchtower)

Automatic security patching via Watchtower:

| Property | Value |
|----------|-------|
| Schedule | Daily at 3am (configurable) |
| Restart | Rolling restarts for zero downtime |
| Containers | PostgreSQL, Redis, Caddy, Backend |
| Cleanup | Old images automatically removed |

### Legacy Encryption (Local Development)

For environments without GCP, Fernet encryption provides fallback:

| Property | Value |
|----------|-------|
| Algorithm | Fernet (AES-128-CBC with HMAC-SHA256) |
| Key Derivation | PBKDF2 from `SECRET_KEY` environment variable |
| Key Size | 256-bit derived key |
| Implementation | `cryptography` library (PyCA) |
| Location | `backend/app/core/encryption.py` |

### Rate Limiting

API endpoints are protected against abuse:

| Limit | Value |
|-------|-------|
| Default | 500 requests/minute per IP |
| Implementation | slowapi middleware |
| Response on Exceeded | HTTP 429 with Retry-After header |

### Security Headers

All API responses include government-grade security headers:

| Header | Value | Purpose |
|--------|-------|---------|
| X-Frame-Options | DENY | Prevent clickjacking |
| X-Content-Type-Options | nosniff | Prevent MIME sniffing |
| X-XSS-Protection | 1; mode=block | Legacy XSS protection |
| Referrer-Policy | strict-origin-when-cross-origin | Control referrer leakage |
| Content-Security-Policy | frame-ancestors 'none' | Prevent framing |
| Cache-Control | no-store (API routes) | Prevent caching sensitive data |

### Infrastructure Security

| Layer | Protection |
|-------|------------|
| Transport | Automatic HTTPS via Caddy (Let's Encrypt) |
| API Secrets | Environment isolation, never in version control |
| Database | PostgreSQL in private Docker network |
| CORS | Configurable Cross-Origin Resource Sharing |

### Input Validation
- Pydantic schema validation on all API inputs
- SQL injection protection via SQLAlchemy ORM
- XSS prevention through React's built-in escaping

### Vertex AI Security

AI analysis is powered by **Google Cloud Vertex AI** with enterprise-grade security:

| Feature | Protection |
|---------|------------|
| **Data Residency** | Processing stays within configured GCP region (no cross-border transfers) |
| **Encryption** | TLS 1.3+ in transit, AES-256 at rest |
| **No Training on Customer Data** | Your data is NEVER used to train Google's models |
| **Audit Logging** | All API calls logged in Cloud Audit Logs |
| **Certifications** | SOC 1/2/3, ISO 27001, FedRAMP, HIPAA eligible |
| **Access Control** | Service Account with minimal IAM permissions |

#### Human-in-the-Loop Priority Scoring

AI priority suggestions follow a **strict human accountability model**:

| Stage | Behavior |
|-------|----------|
| **AI Analysis** | Gemini generates priority score (1-10) stored in `ai_analysis` JSON field |
| **Display** | Staff sees "AI Suggested: X.X" with prominent Accept button |
| **Acceptance** | Staff must explicitly click "Accept AI Priority" to confirm |
| **Audit Trail** | Acceptance creates audit log entry: `action=priority_accepted` |
| **Override** | Staff can set manual priority at any time, superseding AI suggestion |

**Key Liability Protections:**
- AI scores are **suggestions only** and never automatically become official priority
- Complete audit trail of who accepted which AI suggestion and when
- Manual override capability ensures human judgment prevails
- No automatic actions taken based solely on AI assessment

---

## 3. Known Gaps & Vulnerabilities

| Area | Current State | Risk | Remediation |
|------|---------------|------|-------------|
| **MFA** | ✅ **Implemented** (Zitadel Cloud SSO) | Resolved | TOTP, passkeys, biometric via Zitadel |
| **Rate Limiting** | ✅ **Implemented** (slowapi 500/min) | Resolved | N/A |
| **Encryption at Rest** | ✅ **Implemented** (GCP KMS + Fernet fallback) | Resolved | N/A |
| **PII Encryption** | ✅ **Implemented** (Google Cloud KMS) | Resolved | HSM-backed AES-256-GCM |
| **Secrets Management** | ✅ **Implemented** (Google Secret Manager) | Resolved | Bundled secrets with audit logging |
| **AI Human-in-the-Loop** | ✅ **Implemented** | Resolved | AI priority requires explicit staff acceptance |
| **Vertex AI Security** | ✅ **Enterprise-grade** (GCP Vertex AI) | Resolved | SOC/FedRAMP compliant, no data training |
| **Container Updates** | ✅ **Implemented** (Watchtower) | Resolved | Automatic security patches at 3am daily |
| **Security Scanning** | ✅ **Implemented** (CodeQL, Trivy, ZAP) | Resolved | Automated on every push + weekly |
| **Dependency Updates** | ✅ **Implemented** (Dependabot) | Resolved | Weekly auto-PRs for vulnerable deps |
| **Uptime Monitoring** | ✅ **Implemented** (GitHub Actions) | Resolved | 15-min health checks with alerting |
| **Error Tracking** | ✅ **Implemented** (Sentry SDK) | Resolved | Set SENTRY_DSN to enable |
| **Compliance Docs** | ✅ **Implemented** | Resolved | SSP and PIA in /docs folder |
| Audit Retention | Permanent (no purge) | Low | Implement configurable archival policy |
| PII in Comments | Text input only | Moderate | Add AI/regex PII scanning for public fields |


---

## 4. Security Automation (CI/CD)

### GitHub Actions Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| **Build & Publish** | `build-publish.yml` | Push to main | Multi-arch Docker builds + Trivy scan |
| **CodeQL** | `codeql.yml` | Push/PR + weekly | Static security analysis (SAST) |
| **Security Scan** | `security-scan.yml` | Push + weekly | OWASP ZAP (DAST) + Trivy repo scan |
| **Uptime Monitor** | `uptime-monitor.yml` | Every 15 min | Health checks + auto-issue on failure |

### Dependency Management (Dependabot)

Configured in `.github/dependabot.yml`:
- **pip** (backend): Weekly security updates
- **npm** (frontend): Weekly security updates  
- **Docker**: Base image updates
- **GitHub Actions**: Workflow action updates

### Container Scanning (Trivy)

Every Docker image build includes Trivy vulnerability scanning:
- Scans for CRITICAL and HIGH CVEs
- Results uploaded to GitHub Security tab
- Blocks deployment of vulnerable images

### Dynamic Security Testing (OWASP ZAP)

Weekly penetration testing via OWASP ZAP:
- Baseline scan against production endpoints
- Automated issue creation for findings
- HTML report saved as workflow artifact

### Error Tracking (Sentry)

Optional Sentry SDK integration:
```bash
# Add to production environment
SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
```
- 10% trace sampling for performance monitoring
- PII not sent (disabled by default)
- Environment-aware reporting

### Compliance Documentation

| Document | Path | Purpose |
|----------|------|---------|
| System Security Plan | `docs/SECURITY_PLAN.md` | NIST 800-53 control mapping |
| Privacy Impact Assessment | `docs/PRIVACY_ASSESSMENT.md` | Data collection and protection |

---

## 5. Remediation Roadmap

### Remaining Items

| Priority | Item | Effort |
|----------|------|--------|
| Low | Audit Retention Policy | Add configurable archival |
| Medium | PII Scanning in Comments | Regex + optional Vertex AI detection |

---

## Compliance Checklist

### Municipal IT Requirements
- [ ] Passed security assessment
- [ ] Data retention policy documented
- [ ] Incident response plan established
- [ ] Staff training completed

### Technical Verification
- [x] HTTPS enforced in production
- [x] Audit logging enabled
- [x] Password hashing verified (bcrypt)
- [x] Role separation implemented
- [x] Penetration testing completed (OWASP ZAP automated)
- [x] Backup/restore procedure tested
- [x] Security scanning implemented (CodeQL, Trivy, Dependabot)

---

## 6. Accessibility (WCAG 2.2 AA)

| Standard | Status |
|----------|--------|
| 4.1.2 Name, Role, Value | ✅ All interactive elements have aria-labels |
| 1.4.3 Contrast | ✅ Minimum 4.5:1 ratio |
| 2.1.1 Keyboard | ✅ Full keyboard navigation |
| 2.4.4 Link Purpose | ✅ Descriptive link text |

**Pending:** Screen reader testing, axe-core audit

---

## 7. Automated Setup Scripts

Pinpoint 311 includes one-command setup scripts to minimize deployment friction:

### Google Cloud Platform Setup
```bash
./scripts/setup_gcp.sh [PROJECT_ID] [LOCATION]
```

**Automatically configures:**
| Service | Purpose |
|---------|---------|
| Cloud KMS | PII encryption keys |
| Cloud Translation API | 130+ language support |
| Vertex AI | AI analysis (Gemini Flash) |
| Secret Manager | Credential storage |

### Zitadel Cloud SSO Setup
```bash
./scripts/setup_zitadel.sh [DOMAIN] [TOKEN] [APP_DOMAIN]
```

**Automatically configures:**
- Creates Zitadel project and web application
- Configures redirect URLs for production and development
- Outputs credentials for Admin Console

### Prerequisites
- `gcloud` CLI installed and authenticated
- Zitadel Cloud account (free tier available)
- GCP project with billing enabled

---

## 8. Contact & Resources

- **Repository**: [GitHub](https://github.com/WestWindsorForward/WWF-Open-Source-311-Template)
- **API Documentation**: `/api/docs` (Swagger UI)
- **Security Issues**: Report privately via GitHub Security Advisories

---

*Document Version: 1.2 | Last Updated: February 2026*

