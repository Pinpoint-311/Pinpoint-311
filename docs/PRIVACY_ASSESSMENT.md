# Privacy Impact Assessment (PIA)
## Pinpoint 311 - Civic Request Management System

**Version:** 1.0  
**Last Updated:** February 2026  
**Prepared by:** System Administrator

---

## 1. System Description

**Pinpoint 311** enables residents to submit service requests (potholes, streetlight outages, etc.) to their municipality. Staff members process these requests and communicate resolution status.

---

## 2. Information Collected

| Data Element | Purpose | Retention |
|--------------|---------|-----------|
| Name | Identify requester | Per state retention law |
| Email | Send updates; with the Resident History module on, match a resident's earlier requests (§3.1) | Per state retention law |
| Phone (optional) | Alternative contact | Per state retention law |
| Address | Request location. Not collected for categories an administrator sets to "Not collected" | Per state retention law |
| Email / name fingerprints | Resident History lookups only (§3.1); a keyed one-way HMAC, not the value. Exist only while the module is on | Erased when the module is turned off, and when the email or name is scrubbed under retention |
| Photos | Document issue | Per state retention law |
| IP Address | Security/audit | 90 days |

### 2.1 Sensitive Data
- No Social Security Numbers collected
- No financial information collected
- No health information collected
- No biometric data collected

---

## 3. Information Use

Data is used solely for:
1. Processing and resolving service requests
2. Communicating status updates to requesters
3. Generating anonymized analytics for municipal planning
4. Security auditing and incident response
5. When the municipality enables it, showing staff a resident's earlier requests (§3.1)

### 3.1 Resident History module (optional, off by default)

**Purpose.** Lets staff handling a request see the same resident's other
requests, and find requests by a resident's exact email address or full name,
so related reports are handled consistently. It is a use of the data for
processing and resolving service requests; it is off unless an administrator
turns it on under Modules, and that choice is recorded in the audit log.

**How matching works without weakening encryption.** Resident name, email
and phone remain encrypted (AES-256-GCM, random nonce per value, data key
wrapped by the configured KMS). Matching uses separate fingerprint columns:
HMAC-SHA256 of the normalised email and of the normalised full name, under a
random 256-bit key that is itself wrapped by the same KMS envelope. Without
that key a fingerprint reveals nothing, and it cannot be reversed into the
value. A single first or last name is never fingerprinted.

**Controls, all enforced server-side.**

| Control | Detail |
|---------|--------|
| Opt-in | Module off by default; endpoints answer 404 while it is off. Fingerprints are only created while it is on, and are erased when it is turned off |
| Least privilege | Staff and administrators only, limited to requests their department scoping already permits |
| Data minimisation | Returns request number, category, status and date only — never another request's description, location or contact details |
| Exact match only | Full email address or full name; no partial or fuzzy search over PII |
| Accountability | Every lookup writes an audit event (`resident_history_viewed`, `resident_search`) with actor, request or search type, and result count — never the searched value. If the audit write fails, no results are returned |
| No PII in URLs | Search is a POST; values never appear in URLs, proxy logs or browser history |
| Abuse limits | Rate limited per client |
| Retention | Scrubbing a request's email or name clears its fingerprints, so archived requests cannot be linked to a resident |
| No disclosure outward | Fingerprints are never included in exports, work orders or connector payloads |

**Residual risk.** Someone holding both a database copy and access to the
KMS key could test whether a specific email filed requests. That is no more
than they could learn by decrypting the email column itself with the same
access.

---

## 4. Information Sharing

| Recipient | Purpose | Legal Basis |
|-----------|---------|-------------|
| Municipal staff | Request handling | Legitimate interest |
| Department managers | Routing/assignment | Legitimate interest |
| Public (if opted-in) | Transparency | Consent |

**No data sold to third parties.**

### 4.1 Research pack switches — what they do and do not control

The Research & Analytics Lab groups its export columns into packs
(Social Equity, Environmental Context, Sentiment & Trust, Bureaucratic
Friction, AI/ML Research, Moderation) that an administrator can switch on
or off per town.

- **Pack off = never exported AND never computed.** A disabled pack's data
  is not generated and then hidden — it is never generated at all. No
  sentiment score is computed over a resident's message, no request leaves
  for the Census Bureau, CDC SVI, or weather APIs, and nothing derived for
  that pack is written to the database or to disk. Because the data never
  comes into existence, there is no record of it to disclose under
  public-records (e.g. OPRA) requests. This holds for the researcher
  exports, the admin staff export, and the AI analytics chat alike.
- **Enabled packs cache only in process memory.** Census/ACS, CDC SVI, and
  geocoder results for *enabled* packs are memoized in in-process
  dictionaries to limit repeated API calls; they are never persisted to the
  database or filesystem and vanish on restart.
- **Operational records are governed by their own switches.** Intake
  content-moderation flags (`flagged`/`flag_reason`) and AI triage results
  (`ai_summary`, `ai_analysis`) are stored by those day-to-day operational
  features under their own feature switches (the moderation wordlist at
  intake; the "ai" capability switch). The research pack switches control
  only whether exports **disclose** those stored fields. The stored
  operational records themselves remain in the database and are subject to
  records requests like any other operational record.

---

## 5. Data Protection Measures

### 5.1 Technical Controls
- TLS 1.3 encryption in transit
- AES-256 encryption at rest
- Role-based access control, with department scoping for staff
- Audit logging of every change, every export containing resident PII, and
  every Resident History lookup. Ordinary viewing of a single request by its
  assigned staff is not individually logged

### 5.2 Administrative Controls
- Staff security training requirements
- Background checks for system administrators
- Incident response procedures documented

### 5.3 Physical Controls
- Cloud-hosted infrastructure (Oracle Cloud)
- Data center certifications: SOC 2, ISO 27001

---

## 6. Individual Rights

Residents may:
- **Access**: View their submitted requests
- **Correct**: Update contact information
- **Delete**: Request account deletion (subject to retention laws)
- **Opt-out**: Disable email notifications

**To exercise rights:** Contact municipal administration

---

## 7. Retention and Disposal

| Data Type | Retention Period | Disposal Method |
|-----------|------------------|-----------------|
| Service requests | Per state law (3-10 years) | Automated purge |
| Audit logs | 7 years | Automated purge |
| Session data | 24 hours | Auto-expire |
| Uploaded photos | Per state law | Secure deletion |

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Unauthorized access | Low | High | MFA, RBAC, audit logs |
| Data breach | Low | High | Encryption, monitoring |
| Data loss | Low | Medium | Daily backups |
| Misuse by staff | Low | Medium | Audit logs, training; Resident History lookups individually audited and department-scoped |

---

## 9. Compliance

This system complies with:
- [x] State public records laws
- [x] Municipal data governance policies
- [x] WCAG 2.1 AA accessibility standards
- [x] NIST 800-53 security controls

---

## 10. Approval

**Privacy Officer:** ____________________  
**Date:** ____________________

**System Owner:** ____________________  
**Date:** ____________________
