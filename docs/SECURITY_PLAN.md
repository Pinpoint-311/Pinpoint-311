# System Security Plan (SSP)
## Pinpoint 311 - Civic Request Management System

**Version:** 1.0  
**Last Updated:** February 2026  
**Classification:** Public

---

## 1. System Overview

**Pinpoint 311** is an Open311-compliant civic engagement platform enabling residents to submit service requests and municipal staff to manage, route, and resolve them.

### System Components
| Component | Technology | Purpose |
|-----------|------------|---------|
| Frontend | React/TypeScript | User interface |
| Backend | FastAPI/Python | REST API |
| Database | PostgreSQL + PostGIS | Data storage |
| Cache | Redis | Session/cache |
| Reverse Proxy | Caddy | HTTPS termination |

---

## 2. Security Controls

### 2.1 Access Control (AC)
- **AC-2**: Auth0 SSO with role-based access (admin, staff, resident)
- **AC-3**: API endpoints protected by JWT authentication
- **AC-7**: Account lockout after failed login attempts (Auth0 managed)
- **AC-17**: Emergency access with cryptographic tokens

### 2.2 Audit and Accountability (AU)
- **AU-2**: All authentication events logged
- **AU-3**: Logs include timestamp, user, IP, action, result
- **AU-6**: Audit logs viewable in Admin Console
- **AU-9**: Logs stored in PostgreSQL with retention policies

### 2.3 Configuration Management (CM)
- **CM-2**: Infrastructure as Code (Docker Compose)
- **CM-3**: GitHub Actions CI/CD with approval gates
- **CM-6**: Environment-based configuration

### 2.4 Identification and Authentication (IA)
- **IA-2**: Multi-factor authentication via Auth0
- **IA-5**: Password policies enforced by IdP
- **IA-8**: OAuth 2.0 / OIDC standards

### 2.5 System and Communications Protection (SC)
- **SC-8**: TLS 1.3 for all communications (Caddy auto-HTTPS)
- **SC-12**: Encryption keys managed via environment variables
- **SC-13**: AES-256-GCM for secrets at rest
- **SC-28**: Data encrypted at rest (PostgreSQL)

### 2.6 System and Information Integrity (SI)
- **SI-2**: Dependabot automatic security updates
- **SI-3**: Trivy container vulnerability scanning
- **SI-4**: CodeQL static analysis
- **SI-5**: OWASP ZAP dynamic security testing

### 2.7 Workload Identity Federation (Keyless Access)
- **WIF-1**: No long-lived GCP service account keys stored in production
- **WIF-2**: Auth0 OIDC tokens exchanged for short-lived GCP credentials (1 hour expiry)
- **WIF-3**: Bootstrap keys self-destruct after federation verification
- **WIF-4**: All federation events logged to audit trail
- **WIF-5**: Centralized access revocation via Auth0 tenant management


---

## 3. Network Architecture

```
Internet → Caddy (443) → Backend (8000)
                       → Frontend (5173)
         
Backend → PostgreSQL (5432)
        → Redis (6379)
```

All internal services communicate over Docker network; only ports 80/443 exposed externally.

---

## 4. Data Flow

1. **Resident submits request** → Frontend → Backend API → PostgreSQL
2. **Staff views request** → Auth0 SSO → Backend (JWT validated) → Database
3. **AI Analysis** (optional) → Backend → Google Vertex AI → Response stored

---

## 5. Incident Response

| Severity | Response Time | Escalation |
|----------|---------------|------------|
| Critical | 1 hour | Immediate admin notification |
| High | 4 hours | Same-day response |
| Medium | 24 hours | Next business day |
| Low | 72 hours | Scheduled maintenance |

**Contact:** System Administrator via emergency access portal

---

## 6. Continuous Monitoring

| Tool | Frequency | Purpose |
|------|-----------|---------|
| Dependabot | Weekly | Dependency updates |
| CodeQL | On push | Static analysis |
| Trivy | On build | Container CVEs |
| OWASP ZAP | Weekly | Penetration testing |
| Sentry | Real-time | Error tracking |

---

## 7. Authorization

This system is authorized for use by [Municipality Name] for processing civic service requests. No classified or sensitive PII is processed beyond what is necessary for request handling.

**Authorizing Official:** ____________________  
**Date:** ____________________
