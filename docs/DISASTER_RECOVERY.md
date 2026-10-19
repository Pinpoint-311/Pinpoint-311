# Disaster Recovery Runbook

This document outlines procedures for backup, recovery, and disaster response for the Pinpoint 311 system.

## Table of Contents
1. [Backup Overview](#backup-overview)
2. [Manual Backup Procedure](#manual-backup-procedure)
3. [Disaster Recovery Drill](#disaster-recovery-drill)
4. [Emergency Restore Procedure](#emergency-restore-procedure)
5. [Contact Information](#contact-information)

---

## Backup Overview

### Automated Backups
- **Setup**: Admin Console → Setup & Integration → Automatic backups (endpoint, bucket, keys, encryption passphrase; **Save & Test** checks them)
- **Frequency**: Daily at 02:00 UTC, run by the worker
- **Format**: `pg_dump -Fc`, encrypted with GPG (AES-256), uploaded to the bucket root as `db_backup_YYYYMMDD_HHMMSS.sql.gpg`
- **Storage**: S3-compatible storage (AWS S3, Backblaze B2, Oracle Object Storage, etc.)
- **Retention**: Old backups are removed weekly according to the town's records-retention setting. If retention is not configured, every backup is kept.

### What's Backed Up
| Component | Backed Up | Method |
|-----------|-----------|--------|
| PostgreSQL Database | Yes | Encrypted `pg_dump -Fc` to S3-compatible storage |
| Files uploaded through the console (`uploads_data` volume) | No | Back up the Docker volume separately |
| Credentials | Depends | Kept in the chosen secret store; in the database store they are inside the database backup |
| `.env` (`SECRET_KEY`, `DB_PASSWORD`, ...) | No | Keep a copy off the server; `SECRET_KEY` is needed to read database-stored credentials and locally wrapped PII |
| Docker Images | Yes | GHCR (versioned with SHA) |

### Deployment-Triggered Backups

The **Version Switcher** in the Admin Console automatically creates a database backup before every deployment:

| Trigger | Location | Retention |
|---------|----------|-----------|
| Version deployment | `/project/backups/` | Preserved for recovery |
| Format | `pg_dump` compressed SQL | Timestamped filename |

These backups provide an additional recovery point specifically tied to version changes, enabling rollback to the exact database state before a deployment.

Separately, the container entrypoint takes an unencrypted `pg_dump` into the `migration_backups` volume before applying any schema migration, and keeps the newest three.

### What's NOT Backed Up (Ephemeral)
- Redis cache (rebuilds automatically)
- Session tokens (users re-login)
- Celery task queue (persisted to the `redis_data` volume, but not included in off-site backups)

---

## Manual Backup Procedure

### Via Admin Console
1. Navigate to **Admin Console → Compliance → Database Backups**
2. Click **"Create Backup Now"**
3. Wait for confirmation (typically 1-5 minutes)
4. Verify backup appears in backup list

### Via API
```bash
# Trigger backup
curl -X POST https://<YOUR_DOMAIN>/api/system/backups/create \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# List backups
curl https://<YOUR_DOMAIN>/api/system/backups \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Via SSH (Emergency)
```bash
# SSH to production server
ssh ubuntu@<YOUR_SERVER_IP>

# From the directory holding docker-compose.yml. DB_USER and DB_NAME default to
# township and township_db; use the values from your .env if you changed them.
docker compose exec -T db pg_dump -U township -Fc township_db \
  > emergency_backup_$(date +%Y%m%d_%H%M%S).dump

# This file is NOT encrypted. Encrypt it before it leaves the server, e.g.:
gpg --symmetric --cipher-algo AES256 emergency_backup_*.dump
```

---

## Disaster Recovery Drill

**Recommended Frequency**: Quarterly

### Pre-Drill Checklist
- [ ] Schedule 2-hour maintenance window
- [ ] Notify stakeholders
- [ ] Ensure backup is less than 24 hours old
- [ ] Have SSH access credentials ready
- [ ] Have database password available

### Drill Procedure

#### Step 1: Create Fresh Backup (5 min)
```bash
# Via Admin Console or API
curl -X POST https://<YOUR_DOMAIN>/api/system/backups/create \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Step 2: Spin Up Test Environment (15 min)
```bash
# Clone repo on a test server
git clone https://github.com/Pinpoint-311/Pinpoint-311.git
cd Pinpoint-311

# Copy production .env (same SECRET_KEY, so database-stored credentials and
# locally wrapped PII stay readable), but keep the test server off the
# production hostname
cp /path/to/production/.env .env
sed -i 's/^DOMAIN=.*/DOMAIN=localhost/' .env

# Start services
docker compose up -d --build
```

#### Step 3: Download Backup from S3 (5 min)
```bash
# List available backups (add --endpoint-url for non-AWS providers such as Backblaze B2)
aws s3 ls s3://your-backup-bucket/

# Download the newest one
aws s3 cp s3://your-backup-bucket/db_backup_YYYYMMDD_HHMMSS.sql.gpg ./restore.sql.gpg

# Decrypt with the backup encryption passphrase
gpg --decrypt --output restore.dump restore.sql.gpg
```

#### Step 4: Restore Database (10 min)
```bash
# Stop the API and worker to prevent writes
docker compose stop backend worker

# Restore (custom-format dump, so pg_restore rather than psql)
docker compose exec -T db pg_restore -U township -d township_db --clean --if-exists < restore.dump

# Restart services
docker compose up -d
```

Alternatively, once the test instance has the same backup settings, restore from
**Admin Console → Compliance → Database Backups**.

#### Step 5: Verify Data Integrity (15 min)
- [ ] Login to Staff Dashboard works
- [ ] Recent requests are visible
- [ ] Request count matches production
- [ ] Audit logs are intact
- [ ] Service categories load correctly
- [ ] Map layers display properly

#### Step 6: Document Results
```markdown
## DR Drill Results - [DATE]

**Backup Used**: [filename]
**Backup Age**: [hours since backup]
**Restore Time**: [minutes]
**Data Verified**: [yes/no]
**Issues Found**: [list any issues]
**Conducted By**: [name]
```

#### Step 7: Cleanup
```bash
# Destroy test environment
docker compose down -v
cd ..
rm -rf Pinpoint-311
```

---

## Emergency Restore Procedure

### Scenario: Production Database Corrupted/Lost

**RTO (Recovery Time Objective)**: 1 hour
**RPO (Recovery Point Objective)**: 24 hours (based on backup frequency)

#### Immediate Actions
1. **Assess Damage** - Is this corruption or hardware failure?
2. **Notify Stakeholders** - Email/call department heads
3. **Enable Maintenance Mode** - Show friendly error page

#### Restore Steps

```bash
# 1. SSH to production
ssh ubuntu@<YOUR_SERVER_IP>
cd /path/to/app

# 2. Stop all services
docker compose down

# 3. Download and decrypt the latest backup
aws s3 cp s3://your-backup-bucket/db_backup_YYYYMMDD_HHMMSS.sql.gpg ./restore.sql.gpg
gpg --decrypt --output restore.dump restore.sql.gpg

# 4. Start only the database
docker compose up -d db

# 5. Drop and recreate the database (DESTRUCTIVE). Defaults shown; use your .env values.
docker compose exec -T db psql -U township -d postgres -c "DROP DATABASE IF EXISTS township_db;"
docker compose exec -T db psql -U township -d postgres -c "CREATE DATABASE township_db;"

# 6. Restore the backup
docker compose exec -T db pg_restore -U township -d township_db < restore.dump

# 7. Start all services (the entrypoint brings the schema up to the image's version)
docker compose up -d

# 8. Verify system health
curl https://<YOUR_DOMAIN>/api/health/quick
```

#### Post-Recovery
1. Verify all data is intact
2. Check audit logs for last entries before incident
3. Document what was lost (if any)
4. Conduct root cause analysis
5. Update this runbook if needed

---

## Contact Information

| Role | Name | Contact |
|------|------|---------|
| System Admin | [TBD] | [TBD] |
| Database Admin | [TBD] | [TBD] |
| On-Call Engineer | [TBD] | [TBD] |

### Vendor Escalation Directory

> These contacts can help even if the original developer is unavailable.

#### Identity & Authentication (Auth0)
| Resource | URL/Contact |
|----------|-------------|
| Auth0 Status | https://status.auth0.com/ |
| Auth0 Support | https://support.auth0.com/ (paid plans) |
| Auth0 Community | https://community.auth0.com/ |

#### Google Cloud Platform
| Resource | URL/Contact |
|----------|-------------|
| GCP Status | https://status.cloud.google.com/ |
| GCP Console | https://console.cloud.google.com/ |
| Vertex AI Docs | https://cloud.google.com/vertex-ai/docs |

#### PostgreSQL Emergency Help
| Resource | URL/Contact |
|----------|-------------|
| PostgreSQL Wiki | https://wiki.postgresql.org/wiki/Emergency_Recovery |
| Crunchy Data | https://www.crunchydata.com/support |
| Freelance DBAs | Upwork, Toptal (search "PostgreSQL DBA emergency") |

#### Docker/DevOps Contractors
| Resource | Best For |
|----------|----------|
| **Upwork** | Quick fixes, hourly work |
| **Toptal** | Senior DevOps engineers |
| **Fiverr Pro** | Small configuration tasks |

### Emergency Contractor Onboarding Checklist

Before giving a contractor access:
- [ ] Review [ARCHITECTURE.md](./ARCHITECTURE.md) with them
- [ ] Provide read-only access first
- [ ] Create temporary admin credentials (revoke after)
- [ ] Monitor actions in audit logs

### External Status Pages
- **Auth0 Status**: https://status.auth0.com/
- **Sentry Status**: https://status.sentry.io/
- **GitHub Status**: https://www.githubstatus.com/
- **Google Cloud Status**: https://status.cloud.google.com/

---

*Last Updated: February 2026*
*Review Schedule: Quarterly*

## Losing the encryption key

The one failure on this list that no backup fixes.

Resident names, emails and phone numbers are protected by envelope encryption: a
data key encrypts the field, and your cloud's key service wraps that data key.
The database holds the encrypted value and the wrapped data key side by side.
The key service holds the only thing that can unwrap it.

If the key is destroyed, every wrapped data key becomes a sealed box. The
encrypted values remain in the database, intact and meaningless. **Restoring a
backup does not help** — the backup contains the same sealed boxes.

What survives: the report text, category, location, photos, status history and
audit log. All of it. You keep the complete public record of what was reported
and what the town did. What you lose is the ability to say who reported it or to
contact them.

### The failure is silent, and the clock is short

Nothing raises when a key stops answering. `_wrap_dek` falls back to the
application key and carries on, so new reports save normally while older rows
quietly stop being readable. Two consequences:

- It looks like a database fault, not a key fault, because new records are fine.
- If the cause was a scheduled deletion, the cancellation window (7–30 days on
  AWS, the retention period on Azure, the destroy-scheduled-duration on Google)
  can expire before anyone connects the symptom to the cause.

The proactive health scan checks for exactly this every fifteen minutes and
emails admins at critical severity. It performs a live wrap rather than reading
the cached data key, because a long-running worker would otherwise keep
reporting the state of the world from before the key broke — for the whole
window. See `_kms_check` in `app/services/proactive_health.py`.

### The controls guard the key, not the account

Worth being precise, because it is easy to read the list below and conclude the
problem is solved. Every control there stops somebody deleting the *key*. None
of them survives losing the *account* that holds it, and the timelines are all
quiet ones:

| Path | What happens | Window |
|---|---|---|
| Azure subscription canceled | Subscription deleted, resources with it | ~90 days after cancellation |
| AWS account closed | Resources deleted after the post-closure period | 90 days |
| Google project deleted | Takes the key ring; material erased | 30-day destruction window, erased within 45 days |

A `kms:ScheduleKeyDeletion` deny does not apply, because closing an account is
not that call. Purge protection protects a key inside a vault, not a vault
inside a subscription that no longer exists.

For a municipality this is the likelier ending than a mis-click: a card that
expires between budget cycles, a subscription opened on a departing employee's
personal account, a purchasing gap nobody notices until the disable notice
arrives. The controls for it are unglamorous — the account in the town's name on
a town payment method, more than one administrator, billing alerts to a shared
address that is still monitored after somebody leaves.

Two more paths that are *not* deletion and are recoverable, but break decryption
identically and silently:

- **An expiry set on the Azure key.** Key Vault keys support an `exp` attribute,
  after which cryptographic operations are refused. Azure Policy actively
  recommends setting one ("Key Vault keys should have an expiration date"), so a
  well-meaning security review can break PII decryption without deleting
  anything. The key still exists and the date can be extended.
- **The Azure client secret expiring.** Same symptom, different cause, also
  fixable in minutes once identified.

In both cases the `_kms_check` alert fires, which is most of the value: the
failure is recoverable but only if somebody knows it is happening.

### Prevention, in order of value

0. **Protect the container.** Google: place a lien on the project
   (`gcloud alpha resource-manager liens create --restrictions=resourcemanager.projects.delete`),
   which blocks deletion until the lien is removed. Azure: add a `CanNotDelete`
   lock on the vault — locks override user permissions, and an attempt to delete
   the enclosing resource group fails whole rather than half-completing. AWS has
   no equivalent for account closure; billing hygiene is the only control.
1. **Deny the deletion, do not merely avoid it.** On AWS, add an explicit deny
   for `kms:ScheduleKeyDeletion` and `kms:DisableKey` in the key policy — an
   explicit deny cannot be overridden by any allow, including the account root.
   On Azure, enable soft delete and purge protection at vault creation. On
   Google, keys cannot be deleted at all; set the key's destroy scheduled
   duration to its maximum (120 days) and keep
   `cloudkms.cryptoKeyVersions.destroy` off everyday roles.
2. **Set `REQUIRE_KMS`.** The application then refuses to write PII rather than
   silently falling back to the application key. It converts a silent
   divergence into a loud outage, which is the right trade for this data.
3. **Calendar the credential expiry.** Azure client secrets expire. When one
   lapses, decryption stops and nothing about the failure points at a date.
4. **Do not confuse rotation with deletion.** Rotating is safe — old versions
   are retained and keep decrypting old rows — and worth doing. Destroying is
   final. They sit next to each other in every console. On Azure, keep an old
   version *enabled* until the setup page shows no records on it (see "Key
   custody and rotation" below); disabling it early makes those rows
   unreadable until it is re-enabled.

### Key custody and rotation

**Who holds the key.** The key belongs to whoever owns the cloud account it
lives in. Pinpoint's templates create the vault or key in the *town's* (or
county's) own subscription, and the application is given only the right to
wrap and unwrap data keys with it — it cannot read, export, delete or rotate
the key. The town can therefore revoke the application's access at any time,
and nobody outside the town's account holds the key. A pilot whose vault sits
in someone else's account (a vendor's or a contractor's) has handed that
party the key: move it to the town's subscription before real residents' data
is stored, or set the expectation in writing.

**Rotation.** Rotate on whatever schedule the town's policy sets; nothing in
Pinpoint breaks.

- Google Cloud KMS and AWS KMS record the key version inside their own
  ciphertext and decrypt across versions automatically.
- Azure Key Vault does not, so Pinpoint records the version that wrapped each
  data key and unwraps with that version. New data keys move to the new
  version within ten minutes. The nightly re-wrap (`rewrap_pii`) moves
  existing records across, and the setup page counts what is still on an older
  version. When that count is zero, the old version can be disabled.
- Data is never re-encrypted in bulk for a rotation: only the small wrapped
  data keys change.

**Protection against losing it** (cryptographic shredding). Every encrypted
value, and every backup of it, is unreadable without the key, so the key's
survival is the data's survival:

- Azure: soft delete with **purge protection** (recovery level `Recoverable`,
  not `Recoverable+Purgeable`), a `CanNotDelete` lock on the vault, and no
  expiry date set on the key. The proactive health scan reads the first and
  last of these from the key itself every fifteen minutes and alerts if
  purge protection is off or an expiry is near.
- Key Vault keeps keys zone-redundant and replicated to the paired region;
  AWS KMS and Google Cloud KMS are regional and multi-zone. Multi-region
  redundancy is the provider's job, which is why the key lives there.
- The account that holds the key is the single point of failure no setting
  covers (previous section): town-owned, town-billed, more than one admin.

### If it has already happened

Check whether the deletion is still pending. On AWS a scheduled deletion can be
canceled with `CancelKeyDeletion` any time inside the waiting period; on Azure
a soft-deleted key can be recovered within the retention period; on Google a
destroy-scheduled key version can be restored before its scheduled time. In all
three the key stops working at the *start* of that period, so the system being
broken is not evidence that it is too late.

If the window has closed, the encrypted PII is unrecoverable. Everything else in
the database is unaffected, and the service continues to function for new
reports.
