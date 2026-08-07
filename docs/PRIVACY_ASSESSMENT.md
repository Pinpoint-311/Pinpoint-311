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
| Email | Send updates | Per state retention law |
| Phone (optional) | Alternative contact | Per state retention law |
| Address | Request location | Per state retention law |
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
- Role-based access control
- Audit logging of all access

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
| Misuse by staff | Low | Medium | Audit logs, training |

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
